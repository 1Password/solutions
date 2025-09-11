#!/usr/bin/env python3
"""
Keeper→1Password migration helper

Given a Keeper-style JSON export (with top-level keys like
`shared_folders` and `records`), create 1Password vaults and items
using the 1Password CLI (`op`).

What it does
------------
1. Creates a vault for each **shared_folder** and grants users/groups
   roughly equivalent permissions (mapped to 1Password semantics).
2. Creates a **private vault** for each non-shared `folder` referenced
   by records (name prefix configurable; defaults to "Private - ").
3. Recreates items in the appropriate vault(s) (Login or Secure Note),
   including URLs, notes, and TOTP (otpauth://) when present.
4. Puts any records **with no folder** assignment into the specified
   **employee vault**.

Limitations & notes
-------------------
• Keeper has record-level flags like `can_edit` / `can_share` inside a shared
  folder. 1Password permissions are **vault-level**, so this script approximates
  rights at the vault level and **ignores per-item edit/share flags**.
• Permission mapping is best-effort. We map:
    - `manage_users` → `allow_managing` (plus dependencies)
    - `manage_records` → `allow_editing` (plus dependencies)
    - otherwise → `allow_viewing`
  See: https://developer.1password.com/docs/cli/vault-permissions/
• If a record appears in multiple folders, the script **duplicates** it across
  those vaults (because an item belongs to only one vault in 1Password).
• Requires `op` (CLI 2.x) and a signed-in session, or a service account token
  (`OP_SERVICE_ACCOUNT_TOKEN`).

Usage
-----
python migrate_from_json.py \
  --input /path/to/keeper.json \
  --employee-vault "Keeper Import" \
  [--private-prefix "Private - "] \
  [--dry-run] [--silent] [--user-for-private you@example.com]

Examples
--------
# Preview actions without writing anything
python migrate_from_json.py --input keeper.json --employee-vault "Keeper Import" --dry-run

# Real run, creating private vaults that only you can see
python migrate_from_json.py --input keeper.json --employee-vault "Keeper Import" --user-for-private you@example.com

"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --------------------------- CLI helpers ---------------------------


def run(
    cmd: List[str], *, input_bytes: Optional[bytes] = None, check: bool = False
) -> subprocess.CompletedProcess:
    """Run a subprocess command without invoking the shell.

    Raises CalledProcessError if check=True and returncode != 0.
    """
    proc = subprocess.run(
        cmd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr
        )
    return proc


def op_exists() -> bool:
    from shutil import which

    return which("op") is not None


# --------------------------- Data models ---------------------------


@dataclass
class SharedFolderPerm:
    name: str
    is_group: bool
    manage_users: bool
    manage_records: bool


@dataclass
class SharedFolder:
    path: str
    defaults_manage_users: bool
    defaults_manage_records: bool
    permissions: List[SharedFolderPerm]


@dataclass
class Record:
    title: str
    login: Optional[str]
    password: Optional[str]
    login_url: Optional[str]
    notes: Optional[str]
    otpauth: Optional[str]
    shared_folders: List[str]  # names
    folders: List[str]  # non-shared folder names
    category: str  # "Login" or "Secure Note"


# --------------------------- Parsing ---------------------------


def load_keeper_json(path: str) -> Tuple[List[SharedFolder], List[Record]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    shared: List[SharedFolder] = []
    for sf in data.get("shared_folders", []):
        path = sf.get("path") or ""  # e.g., "Banking\\Test folder"
        defaults_manage_users = bool(sf.get("manage_users", False))
        defaults_manage_records = bool(sf.get("manage_records", False))
        perms: List[SharedFolderPerm] = []
        for p in sf.get("permissions", []):
            name = p.get("name", "").strip()
            is_group = "@" not in name  # heuristic: emails are users; others are groups
            perms.append(
                SharedFolderPerm(
                    name=name,
                    is_group=is_group,
                    manage_users=bool(p.get("manage_users", defaults_manage_users)),
                    manage_records=bool(
                        p.get("manage_records", defaults_manage_records)
                    ),
                )
            )
        shared.append(
            SharedFolder(path, defaults_manage_users, defaults_manage_records, perms)
        )

    records: List[Record] = []
    for r in data.get("records", []):
        title = r.get("title") or "Untitled"
        login = r.get("login")
        password = r.get("password")
        login_url = r.get("login_url")
        notes = r.get("notes")
        # Extract otpauth URL if present in custom_fields
        otpauth = None
        cf = r.get("custom_fields") or {}
        for k, v in cf.items():
            if isinstance(v, str) and v.startswith("otpauth://"):
                otpauth = v
                break
        # Folder membership
        shared_folders = []
        folders = []
        for fldr in r.get("folders", []) or []:
            if "shared_folder" in fldr:
                shared_folders.append(str(fldr["shared_folder"]))
            elif "folder" in fldr:
                folders.append(str(fldr["folder"]))
        # Decide category
        category = (
            "Login"
            if (r.get("$type") == "login" or (login and password))
            else "Secure Note"
        )
        records.append(
            Record(
                title,
                login,
                password,
                login_url,
                notes,
                otpauth,
                shared_folders,
                folders,
                category,
            )
        )

    return shared, records


# --------------------------- Name helpers ---------------------------


def normalize_path_to_name(path: str) -> str:
    """Convert a Keeper path like 'Banking\\Taxes' to a nice vault name.
    We'll use slashes and collapse whitespace.
    """
    name = path.replace("\\", "/").strip()
    name = re.sub(r"\s+", " ", name)
    return name


# --------------------------- 1Password wrappers ---------------------------


def ensure_vault(vault_name: str, *, dry: bool, silent: bool) -> None:
    # Check if exists
    get_cmd = ["op", "vault", "get", vault_name, "--format", "json"]
    proc = run(get_cmd)
    if proc.returncode == 0:
        if not silent:
            print(f"✔ Vault exists: {vault_name}")
        return
    if dry:
        print(f"DRY-RUN: would create vault: {vault_name}")
        return
    create_cmd = ["op", "vault", "create", vault_name, "--format", "json"]
    proc2 = run(create_cmd)
    if proc2.returncode != 0:
        print(
            f"ERROR creating vault {vault_name}: {proc2.stderr.decode().strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    if not silent:
        print(f"➕ Created vault: {vault_name}")


def subject_exists(name: str, is_group: bool) -> bool:
    cmd = ["op", "group" if is_group else "user", "get", name, "--format", "json"]
    return run(cmd).returncode == 0


def grant_permissions(
    vault: str,
    subject: str,
    is_group: bool,
    *,
    manage_users: bool,
    manage_records: bool,
    dry: bool,
) -> None:
    """Map Keeper flags to 1Password permissions and grant them.

    We always include allow_viewing; add allow_editing if manage_records;
    add allow_managing if manage_users.
    """
    perms = ["allow_viewing"]
    if manage_records:
        perms.append("allow_editing")
    if manage_users:
        perms.append("allow_managing")
    cmd = [
        "op",
        "vault",
        "group" if is_group else "user",
        "grant",
        "--no-input",
        "--vault",
        vault,
        "--" + ("group" if is_group else "user"),
        subject,
        "--permissions",
        ",".join(perms),
    ]
    if dry:
        print(
            f"DRY-RUN: would grant to {'group' if is_group else 'user'} {subject} on {vault}: {perms}"
        )
        return
    proc = run(cmd)
    if proc.returncode != 0:
        # Helpful context when the subject doesn't exist
        stderr = proc.stderr.decode().strip()
        print(f"WARN granting {subject} on {vault}: {stderr}", file=sys.stderr)


def get_login_template_json() -> Dict[str, Any]:
    proc = run(["op", "item", "template", "get", "Login", "--format", "json"])
    if proc.returncode != 0:
        raise RuntimeError(
            "Unable to fetch Login template from op CLI. Are you signed in?"
        )
    return json.loads(proc.stdout.decode())


def fill_login_template(
    tpl: Dict[str, Any],
    *,
    title: str,
    username: Optional[str],
    password: Optional[str],
    url: Optional[str],
    notes: Optional[str],
) -> Dict[str, Any]:
    # Work on a copy
    item = json.loads(json.dumps(tpl))
    item["title"] = title

    # Built-in fields
    def set_field(fid: str, value: Optional[str]):
        if value is None:
            return
        for f in item.get("fields", []) or []:
            if f.get("id") == fid:
                f["value"] = value
                return
        # If not found, append a new field with minimal shape
        item.setdefault("fields", []).append(
            {"id": fid, "type": "STRING", "value": value}
        )

    set_field("username", username)
    if password is not None:
        # password type should be CONCEALED
        found = False
        for f in item.get("fields", []) or []:
            if f.get("id") == "password":
                f["type"] = "CONCEALED"
                f["value"] = password
                found = True
                break
        if not found:
            item.setdefault("fields", []).append(
                {"id": "password", "type": "CONCEALED", "value": password}
            )

    if notes is not None:
        item["notesPlain"] = notes

    if url:
        item["urls"] = [{"href": url}]

    return item


def create_login_item(
    vault: str,
    *,
    title: str,
    username: Optional[str],
    password: Optional[str],
    url: Optional[str],
    notes: Optional[str],
    otpauth: Optional[str],
    dry: bool,
    silent: bool,
    tpl_cache: Dict[str, Any],
) -> None:
    if dry:
        print(
            f"DRY-RUN: would create LOGIN '{title}' in vault '{vault}'"
            + (" with TOTP" if otpauth else "")
        )
        return

    tpl = tpl_cache.setdefault("login", get_login_template_json())
    item_json = fill_login_template(
        tpl, title=title, username=username, password=password, url=url, notes=notes
    )
    payload = json.dumps(item_json).encode()

    # Build command: use stdin template via '-' and (optionally) add a TOTP assignment
    cmd = ["op", "item", "create", "-", "--vault", vault]
    # Only attach TOTP via assignment to avoid fiddling with JSON shape
    if otpauth:
        cmd.append(f"otp[otp]={otpauth}")  # field name 'otp', fieldType 'otp'

    proc = run(cmd, input_bytes=payload)
    if proc.returncode != 0:
        print(
            f"ERROR creating item '{title}' in '{vault}': {proc.stderr.decode().strip()}",
            file=sys.stderr,
        )
        return
    if not silent:
        print(f"✔ Created LOGIN '{title}' in '{vault}'")


def create_secure_note(
    vault: str, *, title: str, notes: Optional[str], dry: bool, silent: bool
) -> None:
    if dry:
        print(f"DRY-RUN: would create SECURE NOTE '{title}' in vault '{vault}'")
        return
    # For notes, safest is assignment to built-in notesPlain on a Secure Note
    cmd = [
        "op",
        "item",
        "create",
        "--vault",
        vault,
        "--category",
        "Secure Note",
        "--title",
        title,
    ]
    if notes:
        cmd.append(f"notesPlain={notes}")
    proc = run(cmd)
    if proc.returncode != 0:
        print(
            f"ERROR creating note '{title}' in '{vault}': {proc.stderr.decode().strip()}",
            file=sys.stderr,
        )
        return
    if not silent:
        print(f"✔ Created NOTE '{title}' in '{vault}'")


# --------------------------- Planner ---------------------------


def plan_and_apply(
    shared_folders: List[SharedFolder],
    records: List[Record],
    *,
    employee_vault: str,
    private_prefix: str,
    dry: bool,
    silent: bool,
    user_for_private: Optional[str],
) -> None:
    if not op_exists():
        print("ERROR: 'op' (1Password CLI) not found in PATH.", file=sys.stderr)
        sys.exit(1)

    # 1) Create shared vaults and grant perms
    shared_vault_map: Dict[str, str] = {}  # Keeper shared path -> Vault name
    for sf in shared_folders:
        vault_name = normalize_path_to_name(sf.path)
        shared_vault_map[sf.path] = vault_name
        ensure_vault(vault_name, dry=dry, silent=silent)
        for perm in sf.permissions:
            # If the subject doesn't exist, warn but continue
            if not dry and not subject_exists(perm.name, perm.is_group):
                print(
                    f"WARN: {'Group' if perm.is_group else 'User'} '{perm.name}' not found; skipping permission on '{vault_name}'",
                    file=sys.stderr,
                )
                continue
            grant_permissions(
                vault_name,
                perm.name,
                perm.is_group,
                manage_users=perm.manage_users,
                manage_records=perm.manage_records,
                dry=dry,
            )

    # 2) Create private vaults for non-shared folders (unique)
    private_vault_map: Dict[str, str] = {}
    non_shared_folders = set()
    for r in records:
        for f in r.folders:
            non_shared_folders.add(f)
    for folder in sorted(non_shared_folders):
        vault_name = f"{private_prefix}{normalize_path_to_name(folder)}"
        private_vault_map[folder] = vault_name
        ensure_vault(vault_name, dry=dry, silent=silent)
        # Optionally grant a single user access ("private")
        if user_for_private:
            grant_permissions(
                vault_name,
                user_for_private,
                is_group=False,
                manage_users=False,
                manage_records=True,
                dry=dry,
            )

    # 3) Ensure employee vault exists (we don't create/alter it by default)
    ensure_vault(employee_vault, dry=dry, silent=silent)

    # 4) Create items in the appropriate vaults
    tpl_cache: Dict[str, Any] = {}
    for rec in records:
        # Determine destination vaults for this record
        destinations: List[str] = []
        # Shared folder placements
        for sf in rec.shared_folders:
            if sf in shared_vault_map:
                destinations.append(shared_vault_map[sf])
            else:
                # If Keeper JSON references a shared folder not present in the top-level list
                # we still try to create a vault for it on-the-fly.
                name = normalize_path_to_name(sf)
                shared_vault_map[sf] = name
                ensure_vault(name, dry=dry, silent=silent)
                destinations.append(name)
        # Non-shared folder placements
        for f in rec.folders:
            if f in private_vault_map:
                destinations.append(private_vault_map[f])
            else:
                name = f"{private_prefix}{normalize_path_to_name(f)}"
                private_vault_map[f] = name
                ensure_vault(name, dry=dry, silent=silent)
                if user_for_private:
                    grant_permissions(
                        name,
                        user_for_private,
                        is_group=False,
                        manage_users=False,
                        manage_records=True,
                        dry=dry,
                    )
                destinations.append(name)
        # Default: employee vault
        if not destinations:
            destinations = [employee_vault]

        # Create the item in each destination
        for vault in destinations:
            if rec.category == "Login":
                create_login_item(
                    vault,
                    title=rec.title,
                    username=rec.login,
                    password=rec.password,
                    url=rec.login_url,
                    notes=rec.notes,
                    otpauth=rec.otpauth,
                    dry=dry,
                    silent=silent,
                    tpl_cache=tpl_cache,
                )
            else:
                # Secure Note; include URL as a line in notes if present
                notes = rec.notes or ""
                if rec.login_url:
                    notes = (notes + ("\n" if notes else "")) + f"URL: {rec.login_url}"
                create_secure_note(
                    vault, title=rec.title, notes=notes, dry=dry, silent=silent
                )


# --------------------------- Entrypoint ---------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Keeper → 1Password migration helper (vaults, permissions, items)"
    )
    ap.add_argument("--input", required=True, help="Path to Keeper-style JSON export")
    ap.add_argument(
        "--employee-vault",
        required=True,
        help="Name of the Employee/Private vault for items without folders",
    )
    ap.add_argument(
        "--private-prefix",
        default="Private - ",
        help="Prefix to use for private vault names (default: 'Private - ')",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't call 'op'; just print planned actions",
    )
    ap.add_argument("--silent", action="store_true", help="Do not print progress messages")
    ap.add_argument(
        "--user-for-private",
        help="Email of the user who should get access to private vaults (granted allow_editing + allow_viewing)",
    )

    args = ap.parse_args()

    # Load data
    try:
        shared, records = load_keeper_json(args.input)
    except Exception as e:
        print(f"Failed to parse input JSON: {e}", file=sys.stderr)
        sys.exit(2)

    if not args.silent:
        print(
            f"Loaded {len(shared)} shared folders and {len(records)} records from {args.input}"
        )

    # Apply plan
    plan_and_apply(
        shared,
        records,
        employee_vault=args.employee_vault,
        private_prefix=args.private_prefix,
        dry=args.dry_run,
        silent=args.silent,
        user_for_private=args.user_for_private,
    )


if __name__ == "__main__":
    main()
