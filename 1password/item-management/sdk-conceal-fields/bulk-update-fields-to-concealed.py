#!/usr/bin/env python3
"""
Make every custom field in all 1Password items CONCEALED.

Two modes:

  BOOTSTRAP (default — no token provided):
    1. Use the `op` CLI (as the currently signed-in user) to list the vaults
       you have Manage permission on.
    2. Create a fresh service account with read_items,write_items on each.
    3. Save the SA token as a Password item in your personal vault, so you
       can re-run within the expiry window without losing access.
    4. Use the SA via the Python SDK to conceal custom fields.

  REUSE (--token TOKEN, or OP_SERVICE_ACCOUNT_TOKEN env var set):
    1. Skip the CLI bootstrap entirely.
    2. Authenticate the SDK with the provided token.
    3. Conceal custom fields in every vault the token can see.

Dry run is the default in both modes. Pass --apply to write changes.
In reuse mode, dry run is a field-level preview (since we already have
SDK access). In bootstrap mode, dry run only previews vault selection
(no SA is created until you commit).

Requirements:
    pip install onepassword-sdk
    For bootstrap mode: 1Password CLI v2.18.0+ installed and signed in.

Service accounts can't be granted access to Personal, Private, Employee,
or the default Shared vault. Items in those will NOT be touched.

Usage:
    python conceal_custom_fields.py                              # preview vault selection
    python conceal_custom_fields.py --apply                      # create SA, save token, conceal fields
    python conceal_custom_fields.py --apply --sa-expires-in 30m
    python conceal_custom_fields.py --apply --save-token-to-vault MyOps
    python conceal_custom_fields.py --token ops_...              # preview field changes
    python conceal_custom_fields.py --token ops_... --apply      # write using existing SA
    OP_SERVICE_ACCOUNT_TOKEN=ops_... python conceal_custom_fields.py --apply

To retrieve a previously saved token:
    op read 'op://VAULT_NAME/SA_NAME/password'
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from onepassword.client import Client
from onepassword.types import ItemFieldType


INTEGRATION_NAME = "conceal-custom-fields"
INTEGRATION_VERSION = "v1.0.0"

# Built-in 1Password vault names — service accounts cannot be granted access
# to any of these per the docs, so we skip them up front.
BUILTIN_VAULT_NAMES: set[str] = {"Personal", "Private", "Employee", "Shared"}

# Permission strings that indicate the user can manage a vault.
MANAGE_PERMISSIONS: set[str] = {"allow_managing", "manage_vault"}

# Well-known built-in field ids that 1Password reserves across categories.
# Custom (user-added) fields get random 26-char ids, so anything not in
# this set is treated as custom.
BUILTIN_FIELD_IDS: set[str] = {
    "username",
    "password",
    "notesPlain",
    "credential",
    "type",
    "filename",
    "validFrom",
    "expires",
    "hostname",
    "url",
    "port",
    "database",
    "sid",
    "alias",
    "options",
    "cardholder",
    "ccnum",
    "cvv",
    "expiry",
    "pin",
    "creditLimit",
    "cashLimit",
    "interest",
    "bank",
    "phoneLocal",
    "phoneTollFree",
    "phoneIntl",
    "website",
    "firstname",
    "initial",
    "lastname",
    "sex",
    "birthdate",
    "occupation",
    "company",
    "department",
    "jobtitle",
    "address",
    "defphone",
    "homephone",
    "cellphone",
    "busphone",
    "email_address",
    "address1",
    "address2",
    "bankName",
    "accountType",
    "routingNo",
    "accountNo",
    "swift",
    "iban",
    "number",
    "fullname",
    "nationality",
    "issuing_country",
    "sex_passport",
    "license_class",
    "conditions",
    "state",
    "country",
    "expiry_date",
}

# Field types we WON'T coerce — either already CONCEALED, or special
# semantics that would corrupt or drop data.
NON_COERCIBLE_TYPES: set[ItemFieldType] = {ItemFieldType.CONCEALED}
for _name in (
    "UNSUPPORTED",
    "TOTP",
    "SSHKEY",
    "ADDRESS",
    "DATE",
    "MONTHYEAR",
    "REFERENCE",
    "MENU",
    "CREDITCARDNUMBER",
    "CREDITCARDTYPE",
    "FILE",
):
    _m = getattr(ItemFieldType, _name, None)
    if _m is not None:
        NON_COERCIBLE_TYPES.add(_m)


# ---------------------------------------------------------------------------
# Bootstrap helpers (sync, talk to the `op` CLI)
# ---------------------------------------------------------------------------


def run_op_cli(args: list[str]) -> str:
    """Run `op <args>` and return stdout. Raises on non-zero exit."""
    result = subprocess.run(["op", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"op {' '.join(shlex.quote(a) for a in args)} failed:\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout


def get_current_user_id() -> str:
    """Return the current user's id from `op whoami`."""
    data = json.loads(run_op_cli(["whoami", "--format", "json"]))
    for key in ("user_uuid", "user_id", "id", "ID"):
        value = data.get(key)
        if value:
            return value
    raise RuntimeError(f"Could not extract user id from `op whoami`: {data}")


def list_all_vaults() -> list[dict[str, Any]]:
    """List every vault the current user has access to."""
    return json.loads(run_op_cli(["vault", "list", "--format", "json"]))


def extract_user_perms(entry: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Pull (user_id, permissions) out of an `op vault user list` entry.

    Handles a few possible JSON shapes since they've varied across CLI versions.
    """
    user_id = (
        entry.get("id")
        or entry.get("user_id")
        or entry.get("user_uuid")
        or (entry.get("user") or {}).get("id")
    )
    perms = entry.get("permissions")
    if isinstance(perms, str):
        perms = [p.strip() for p in perms.split(",") if p.strip()]
    if not isinstance(perms, list):
        perms = []
    return user_id, perms


def user_manages_vault(user_id: str, vault_id: str) -> bool:
    """Check whether the current user has Manage permission on this vault."""
    try:
        raw = run_op_cli(["vault", "user", "list", vault_id, "--format", "json"])
    except RuntimeError:
        return False
    for entry in json.loads(raw):
        entry_user_id, perms = extract_user_perms(entry)
        if entry_user_id != user_id:
            continue
        return any(p in MANAGE_PERMISSIONS for p in perms)
    return False


def find_manageable_vaults(
    user_id: str,
    all_vaults: list[dict[str, Any]],
    concurrency: int,
) -> list[dict[str, Any]]:
    """Vaults the current user manages, excluding built-in ones.

    Permission checks are issued in parallel via a thread pool — the work is
    one subprocess call per vault, so threads are the right tool here.
    """
    candidates: list[dict[str, Any]] = []
    for v in all_vaults:
        if v.get("name", "") in BUILTIN_VAULT_NAMES:
            print(f"  · skip {v['name']!r}: built-in, can't grant to SA")
            continue
        candidates.append(v)

    if not candidates:
        return []

    print(
        f"Checking permissions across {len(candidates)} vault(s) "
        f"(concurrency={concurrency})..."
    )
    manageable: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        future_to_vault = {
            pool.submit(user_manages_vault, user_id, v["id"]): v for v in candidates
        }
        completed = 0
        for future in as_completed(future_to_vault):
            v = future_to_vault[future]
            completed += 1
            try:
                managed = future.result()
            except Exception as exc:
                print(
                    f"  ! [{completed}/{len(candidates)}] {v['name']}: {exc}",
                    file=sys.stderr,
                )
                continue
            if managed:
                manageable.append(v)
                print(f"  ✓ [{completed}/{len(candidates)}] {v['name']}")

    manageable.sort(key=lambda v: v.get("name", "").lower())
    return manageable


SA_TOKEN_RE = re.compile(r"ops_[A-Za-z0-9_\-\.]+")


def find_personal_vault(
    all_vaults: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the user's personal vault.

    Looks for Private, Personal, or Employee in that order. Service accounts
    can't access these, but the human user can — making them the right place
    to store the SA token for later retrieval.
    """
    for preferred in ("Private", "Personal", "Employee"):
        for v in all_vaults:
            if v.get("name") == preferred:
                return v
    return None


def save_token_to_1password(
    token: str,
    vault_name: str,
    title: str,
    expires_in: str,
) -> None:
    """Save the SA token as a Password item via `op item create`.

    Authenticated as the human user (not the SA), so personal/private vaults
    are reachable. Raises on failure — caller decides how to recover.
    """
    notes = (
        f"Service account token created by conceal_custom_fields.py.\n"
        f"Created: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"Expires: {expires_in} after creation.\n"
        f"\n"
        f"To re-run the script within the expiry window:\n"
        f"  OP_SERVICE_ACCOUNT_TOKEN=$(op read "
        f"'op://{vault_name}/{title}/password') \\\n"
        f"      python conceal_custom_fields.py --apply\n"
        f"\n"
        f"Once the SA expires this item is no longer useful — delete it."
    )
    run_op_cli(
        [
            "item",
            "create",
            "--category",
            "password",
            "--vault",
            vault_name,
            "--title",
            title,
            "--tags",
            "conceal-custom-fields",
            f"notesPlain={notes}",
            f"password={token}",
        ]
    )


def create_service_account(
    name: str,
    vaults: list[dict[str, Any]],
    expires_in: str,
) -> str:
    """Create a service account with write access to each vault.

    Returns the SA token. The CLI only prints it once, so the caller is
    responsible for using it immediately or storing it.
    """
    args = [
        "service-account",
        "create",
        name,
        "--expires-in",
        expires_in,
    ]
    for v in vaults:
        args.extend(["--vault", f"{v['id']}:read_items,write_items"])

    out = run_op_cli(args)
    match = SA_TOKEN_RE.search(out)
    if not match:
        raise RuntimeError(
            "Service account was created but the token couldn't be parsed "
            f"from the CLI output:\n{out!r}"
        )
    return match.group(0)


# ---------------------------------------------------------------------------
# Concealment (async, talks to the SDK)
# ---------------------------------------------------------------------------


def is_custom_field(field) -> bool:
    """True if this field is user-added (not a 1Password built-in)."""
    return field.id not in BUILTIN_FIELD_IDS


def item_has_unsupported_field(item) -> bool:
    """Items containing UNSUPPORTED fields can't be round-tripped via put()."""
    unsupported = getattr(ItemFieldType, "UNSUPPORTED", None)
    if unsupported is None:
        return False
    return any(f.field_type == unsupported for f in (item.fields or []))


async def build_sdk_client(token: str) -> Client:
    return await Client.authenticate(
        auth=token,
        integration_name=INTEGRATION_NAME,
        integration_version=INTEGRATION_VERSION,
    )


async def process_item(client: Client, item, apply_changes: bool) -> int:
    """Conceal eligible custom fields on one item. Returns count changed."""
    if item_has_unsupported_field(item):
        print(
            f"  · skipping {item.title!r} ({item.id}): contains an UNSUPPORTED "
            "field type; the SDK can't write this item back."
        )
        return 0

    changed: list[tuple[str, Any]] = []
    for field in item.fields or []:
        if not is_custom_field(field):
            continue
        if field.field_type in NON_COERCIBLE_TYPES:
            continue
        changed.append((field.title or field.id, field.field_type))
        field.field_type = ItemFieldType.CONCEALED  # mutate in place

    if not changed:
        return 0

    print(f"\n• {item.title}  [{item.id}]  — {len(changed)} field(s):")
    for name, old_type in changed:
        old = getattr(old_type, "name", str(old_type))
        print(f"    {old:>12} → CONCEALED   {name}")

    if apply_changes:
        try:
            await client.items.put(item)
        except Exception as exc:
            print(f"    ! put() failed: {exc}", file=sys.stderr)
            return 0

    return len(changed)


async def conceal_with_client(
    client: Client,
    vault_ids: list[str],
    apply_changes: bool,
) -> tuple[int, int]:
    """Walk each vault, conceal eligible custom fields. Returns (items, fields)."""
    total_items = 0
    total_fields = 0

    for vault_id in vault_ids:
        try:
            overviews = list(await client.items.list(vault_id))
        except Exception as exc:
            print(
                f"! could not list items in vault {vault_id}: {exc}",
                file=sys.stderr,
            )
            continue

        for overview in overviews:
            try:
                item = await client.items.get(vault_id, overview.id)
            except Exception as exc:
                print(
                    f"  ! could not fetch {overview.id}: {exc}",
                    file=sys.stderr,
                )
                continue
            changed = await process_item(client, item, apply_changes)
            if changed:
                total_items += 1
                total_fields += changed

    return total_items, total_fields


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


async def run_reuse_mode(token: str, source: str, apply_changes: bool) -> int:
    """Use an existing SA token. Discover vaults via SDK, then process them."""
    print(f"Using existing service account token from {source}.")
    client = await build_sdk_client(token)
    vaults = list(await client.vaults.list())
    if not vaults:
        print("Token has access to 0 vaults — nothing to do.")
        return 0
    print(f"Token has access to {len(vaults)} vault(s):")
    for v in vaults:
        print(f"  - {v.title}  ({v.id})")

    items, fields = await conceal_with_client(
        client,
        [v.id for v in vaults],
        apply_changes,
    )

    verb = "Concealed" if apply_changes else "Would conceal"
    print(f"\n{verb} {fields} field(s) across {items} item(s).")
    if not apply_changes and fields:
        print("Re-run with --apply to commit.")
    return 0


def run_bootstrap_mode(args: argparse.Namespace) -> int:
    """Discover vaults via CLI, optionally create SA, then run concealment."""
    print("Discovering current user...")
    try:
        user_id = get_current_user_id()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"Could not run `op whoami`: {exc}", file=sys.stderr)
        print("Is the op CLI installed and are you signed in?", file=sys.stderr)
        return 1

    all_vaults = list_all_vaults()
    manageable = find_manageable_vaults(user_id, all_vaults, args.concurrency)
    if not manageable:
        print("\nNo manageable vaults found (or all are built-in). Nothing to do.")
        return 0

    print(
        f"\nWill grant the new service account read_items,write_items on "
        f"{len(manageable)} vault(s):"
    )
    for v in manageable:
        print(f"  - {v['name']}  ({v['id']})")

    # Decide where the SA token will live for later retrieval.
    save_vault_name: str | None
    if args.no_save_token:
        save_vault_name = None
    elif args.save_token_to_vault:
        save_vault_name = args.save_token_to_vault
    else:
        personal = find_personal_vault(all_vaults)
        save_vault_name = personal["name"] if personal else None

    if args.no_save_token:
        print("\nToken storage: --no-save-token set. Token will be ephemeral.")
    elif save_vault_name:
        print(
            f"\nToken storage: will save SA token to vault "
            f"{save_vault_name!r} as a Password item (so you can re-run "
            "within the expiry window)."
        )
    else:
        # No personal vault auto-detected and no override given.
        print(
            "\nERROR: could not auto-detect a personal vault "
            "(Private/Personal/Employee) to store the SA token.\n"
            "Pass --save-token-to-vault VAULT_NAME to specify where, or "
            "--no-save-token to skip saving (one-shot use only).",
            file=sys.stderr,
        )
        return 1

    if not args.apply:
        print(
            "\nDry run — re-run with --apply to create the service account "
            "and conceal custom fields."
        )
        return 0

    sa_name = args.sa_name or (
        "conceal-custom-fields-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    print(
        f"\nCreating service account {sa_name!r} "
        f"(expires in {args.sa_expires_in})..."
    )
    try:
        token = create_service_account(sa_name, manageable, args.sa_expires_in)
    except RuntimeError as exc:
        print(f"Could not create service account: {exc}", file=sys.stderr)
        return 1
    print(f"Service account created (expires in {args.sa_expires_in}).")

    # Persist the token before running anything that might fail.
    if save_vault_name:
        try:
            save_token_to_1password(
                token,
                save_vault_name,
                sa_name,
                args.sa_expires_in,
            )
            print(
                f"Token saved to 1Password as item {sa_name!r} in vault "
                f"{save_vault_name!r}."
            )
            print(
                f"\nTo re-run within the expiry window:\n"
                f"  OP_SERVICE_ACCOUNT_TOKEN=$(op read "
                f"'op://{save_vault_name}/{sa_name}/password') \\\n"
                f"      python conceal_custom_fields.py --apply"
            )
        except RuntimeError as exc:
            # The SA exists but we couldn't persist the token. Print it as
            # a last-resort fallback so the user isn't left stranded.
            print(
                f"\nWARNING: could not save token to 1Password: {exc}",
                file=sys.stderr,
            )
            print(
                "Printing token to stdout as fallback — copy it now, it "
                "won't be shown again:\n",
                file=sys.stderr,
            )
            print(token)
            print()
    else:
        print(
            "\nEphemeral mode: token lives only in this process. If "
            "concealment fails partway through, you'll need to create "
            "a new SA to retry."
        )

    async def _run() -> tuple[int, int]:
        client = await build_sdk_client(token)
        return await conceal_with_client(
            client,
            [v["id"] for v in manageable],
            apply_changes=True,
        )

    items, fields = asyncio.run(_run())

    print(f"\nConcealed {fields} field(s) across {items} item(s).")
    print(
        f"\nThe service account {sa_name!r} will auto-expire in "
        f"{args.sa_expires_in}. To revoke or rotate sooner, visit "
        "https://my.1password.com → Developer → Service Accounts."
    )
    if save_vault_name:
        print(
            f"Once the SA expires, the saved item {sa_name!r} in vault "
            f"{save_vault_name!r} is no longer useful — feel free to delete it."
        )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. In bootstrap mode this also creates the "
        "service account. Without this flag, the script previews only.",
    )
    p.add_argument(
        "--token",
        metavar="TOKEN",
        default=None,
        help="Use this service account token instead of creating a new one. "
        "If omitted but OP_SERVICE_ACCOUNT_TOKEN is set in the "
        "environment, that value is used.",
    )
    p.add_argument(
        "--sa-name",
        default=None,
        help="(bootstrap mode) Name for the new service account. "
        "Default: conceal-custom-fields-<timestamp>",
    )
    p.add_argument(
        "--sa-expires-in",
        default="1h",
        help="(bootstrap mode) Service account expiry (e.g. 30m, 1h, 24h). "
        "Default: 1h. SAs can't be deleted via CLI, so the expiry is "
        "the cleanup mechanism.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="(bootstrap mode) Number of parallel `op vault user list` calls "
        "during vault discovery. Default: 10.",
    )
    p.add_argument(
        "--save-token-to-vault",
        metavar="VAULT_NAME",
        default=None,
        help="(bootstrap mode) Save the new SA's token to a Password item in "
        "this vault. Default: auto-detect Private, Personal, or "
        "Employee (in that order).",
    )
    p.add_argument(
        "--no-save-token",
        action="store_true",
        help="(bootstrap mode) Don't save the SA token anywhere — use it "
        "once, in memory only. The SA will still exist until its "
        "expiry, but you won't be able to retry on failure.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Resolve token: explicit --token wins, else env var, else bootstrap.
    token = args.token
    token_source = "--token flag" if token else None
    if not token:
        env_token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
        if env_token:
            token = env_token
            token_source = "OP_SERVICE_ACCOUNT_TOKEN env var"

    if token:
        return asyncio.run(run_reuse_mode(token, token_source, args.apply))
    return run_bootstrap_mode(args)


if __name__ == "__main__":
    sys.exit(main())
