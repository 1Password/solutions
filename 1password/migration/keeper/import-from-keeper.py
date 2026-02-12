#!/usr/bin/env python3
"""
Keeper→1Password migration helper (ZIP with files) — SDK bulk create

Uses the 1Password beta Python SDK for items and vault listing:
- Items.create_all for bulk item creation (max 100 per call).
- Vaults.list(decrypt_details=True) to resolve vault names to IDs.
- Vaults.grant_group_permissions for group vault access (SDK).

Vaults that don't exist are created via the 1Password CLI (`op vault create`).
User vault permissions are granted via the CLI (`op vault user grant`); group
permissions are granted via the SDK.

- Accepts either:
  - A **.zip** file with `export.json` and `files/` (import with attachments).
  - A **.json** file (Keeper export data only; no attachments).
- For ZIP: renames attachment blobs from UID to display name; attaches files to items.
- Permission mapping: Keeper shared_folder permissions → 1Password vault access
  (manage_users → allow_managing, manage_records → allow_editing, else allow_viewing).

Requires: OP_SERVICE_ACCOUNT_TOKEN, onepassword-sdk (beta), and `op` CLI (vault create + user grants).

Usage
-----
python import-with-files-bulk.py \\
  --input /path/to/export-files.zip \\
  --employee-vault "Keeper Import" \\
  [--private-prefix "Private - "] \\
  [--dry-run] [--silent]

  # Or JSON only (no files):
python import-with-files-bulk.py \\
  --input /path/to/export.json \\
  --employee-vault "Keeper Import" \\
  [--dry-run] [--silent]
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import mimetypes
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from shutil import which
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from onepassword.client import Client
from onepassword import (
    AutofillBehavior,
    FileCreateParams,
    GroupAccess,
    ItemCategory,
    ItemCreateParams,
    ItemField,
    ItemFieldType,
    ItemSection,
    ItemsUpdateAllResponse,
    READ_ITEMS,
    REVEAL_ITEM_PASSWORD,
    UPDATE_ITEM_HISTORY,
    CREATE_ITEMS,
    UPDATE_ITEMS,
    ARCHIVE_ITEMS,
    DELETE_ITEMS,
    IMPORT_ITEMS,
    EXPORT_ITEMS,
    SEND_ITEMS,
    PRINT_ITEMS,
    MANAGE_VAULT,
    VaultListParams,
    Website,
)

# --------------------------- Session ---------------------------


async def _get_client() -> Client:
    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
    if not token:
        raise RuntimeError("OP_SERVICE_ACCOUNT_TOKEN is not set")
    return await Client.authenticate(
        auth=token,
        integration_name="Importer",
        integration_version="v1",
    )


def _normalize_vault_name(name: str) -> str:
    """Collapse whitespace and normalize slash so 'A / B' and 'A/B' match."""
    s = " ".join(name.split())
    return s.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")


async def _vault_name_to_id_map(client: Client) -> Tuple[Dict[str, str], List[str]]:
    """List vaults with decrypt_details=True; return (name->id map, list of vault titles)."""
    vaults = await client.vaults.list(VaultListParams(decrypt_details=True))
    name_to_id: Dict[str, str] = {}
    titles: List[str] = []
    for v in vaults:
        name_to_id[v.title] = v.id
        titles.append(v.title)
        normalized = _normalize_vault_name(v.title)
        if normalized != v.title:
            name_to_id[normalized] = v.id
    return name_to_id, sorted(titles)


def _resolve_vault_id(name_to_id: Dict[str, str], vault_name: str) -> str:
    """Resolve vault name to ID using the pre-built map. Raises if not found."""
    if vault_name in name_to_id:
        return name_to_id[vault_name]
    normalized = _normalize_vault_name(vault_name)
    if normalized in name_to_id:
        return name_to_id[normalized]
    # Suggest closest match when vault name is missing (e.g. typo or new vault)
    all_names = list(name_to_id.keys())
    candidates = [n for n in all_names if n != "[Encrypted]"]
    suggestions = difflib.get_close_matches(vault_name, candidates, n=1, cutoff=0.6)
    msg = f"Vault not found: {vault_name!r}."
    if suggestions:
        msg += f" Did you mean {suggestions[0]!r}?"
    msg += f" Available: {', '.join(sorted(candidates)[:15])}"
    if len(candidates) > 15:
        msg += f", ... ({len(candidates)} total)"
    raise ValueError(msg)


def _run_op(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def _op_exists() -> bool:
    return which("op") is not None


def _ensure_vault(vault_name: str, *, dry: bool, silent: bool) -> None:
    """Create vault via CLI if it doesn't exist. No-op if it already exists."""
    proc = _run_op(["op", "vault", "get", vault_name, "--format", "json"])
    if proc.returncode == 0:
        if not silent:
            print(f"✔ Vault exists: {vault_name}")
        return
    if dry:
        print(f"DRY-RUN: would create vault: {vault_name}")
        return
    proc2 = _run_op(["op", "vault", "create", vault_name, "--format", "json"])
    if proc2.returncode != 0:
        print(
            f"ERROR creating vault {vault_name!r}: {proc2.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    if not silent:
        print(f"➕ Created vault: {vault_name}")


# Permission masks for SDK (1Password Business granular permissions)
_PERM_VIEWING = (
    READ_ITEMS | REVEAL_ITEM_PASSWORD | UPDATE_ITEM_HISTORY
)
_PERM_EDITING = _PERM_VIEWING | (
    CREATE_ITEMS | UPDATE_ITEMS | ARCHIVE_ITEMS | DELETE_ITEMS
    | IMPORT_ITEMS | EXPORT_ITEMS | SEND_ITEMS | PRINT_ITEMS
)
_PERM_MANAGING = _PERM_EDITING | MANAGE_VAULT


def _subject_exists(name: str, is_group: bool) -> bool:
    """Return True if the user or group exists in 1Password (via CLI)."""
    kind = "group" if is_group else "user"
    proc = _run_op(["op", kind, "get", name, "--format", "json"])
    return proc.returncode == 0


def _get_group_id_by_name(name: str) -> Optional[str]:
    """Resolve group name to ID via CLI. Returns None if not found."""
    proc = _run_op(["op", "group", "get", name, "--format", "json"])
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
        return data.get("id")
    except (json.JSONDecodeError, TypeError):
        return None


def _perms_list(manage_users: bool, manage_records: bool) -> List[str]:
    """CLI permission names: allow_viewing, allow_editing, allow_managing."""
    perms = ["allow_viewing"]
    if manage_records:
        perms.append("allow_editing")
    if manage_users:
        perms.append("allow_managing")
    return perms


def _grant_user_permissions(
    vault_name: str,
    user_name: str,
    *,
    manage_users: bool,
    manage_records: bool,
    dry: bool,
    silent: bool,
) -> None:
    """Grant vault permissions to a user via CLI."""
    perms = _perms_list(manage_users, manage_records)
    if dry:
        if not silent:
            print(
                f"DRY-RUN: would grant user {user_name!r} on {vault_name!r}: {perms}"
            )
        return
    cmd = [
        "op", "vault", "user", "grant", "--no-input",
        "--vault", vault_name, "--user", user_name,
        "--permissions", ",".join(perms),
    ]
    proc = _run_op(cmd)
    if proc.returncode != 0:
        print(
            f"WARN granting user {user_name!r} on {vault_name!r}: {proc.stderr.strip()}",
            file=sys.stderr,
        )


async def _grant_group_permissions_sdk(
    client: Client,
    vault_id: str,
    group_id: str,
    *,
    manage_users: bool,
    manage_records: bool,
    dry: bool,
    silent: bool,
) -> None:
    """Grant vault permissions to a group via SDK."""
    if manage_users:
        perm_int = _PERM_MANAGING
    elif manage_records:
        perm_int = _PERM_EDITING
    else:
        perm_int = _PERM_VIEWING
    if dry:
        if not silent:
            perms_desc = "allow_managing" if manage_users else ("allow_editing" if manage_records else "allow_viewing")
            print(
                f"DRY-RUN: would grant group {group_id!r} on vault: {perms_desc}"
            )
        return
    try:
        await client.vaults.grant_group_permissions(
            vault_id,
            [GroupAccess(group_id=group_id, permissions=perm_int)],
        )
    except Exception as e:
        print(
            f"WARN granting group on vault {vault_id!r}: {e}",
            file=sys.stderr,
        )


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
class Attachment:
    file_uid: str
    name: Optional[str]
    mime: Optional[str]


@dataclass
class Record:
    title: str
    login: Optional[str]
    password: Optional[str]
    login_url: Optional[str]
    notes: Optional[str]
    otpauth: Optional[str]
    shared_folders: List[str]
    folders: List[str]
    category: str
    attachments: List[Attachment]


# --------------------------- Parsing ---------------------------


def _ext_from_mime(mime: Optional[str]) -> Optional[str]:
    if not mime:
        return None
    ext = mimetypes.guess_extension(mime)
    if ext == ".jpe":
        ext = ".jpg"
    return ext


def load_keeper_json(path: str) -> Tuple[List[SharedFolder], List[Record]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    shared: List[SharedFolder] = []
    for sf in data.get("shared_folders", []):
        path = sf.get("path") or ""
        defaults_manage_users = bool(sf.get("manage_users", False))
        defaults_manage_records = bool(sf.get("manage_records", False))
        perms: List[SharedFolderPerm] = []
        for p in sf.get("permissions", []):
            name = p.get("name", "").strip()
            is_group = "@" not in name
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
        otpauth = None
        cf = r.get("custom_fields") or {}
        for k, v in cf.items():
            if isinstance(v, str) and v.startswith("otpauth://"):
                otpauth = v
                break
        shared_folders = []
        folders = []
        for fldr in r.get("folders", []) or []:
            if "shared_folder" in fldr:
                shared_folders.append(str(fldr["shared_folder"]))
            elif "folder" in fldr:
                folders.append(str(fldr["folder"]))
        category = (
            "Login"
            if (r.get("$type") == "login" or (login and password))
            else "Secure Note"
        )
        attachments_raw = r.get("attachments") or []
        attachments: List[Attachment] = [
            Attachment(
                file_uid=a.get("file_uid", ""),
                name=a.get("name"),
                mime=a.get("mime"),
            )
            for a in attachments_raw
            if a.get("file_uid")
        ]

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
                attachments,
            )
        )

    return shared, records


def normalize_path_to_name(path: str) -> str:
    name = path.replace("\\", "/").strip()
    name = re.sub(r"\s+", " ", name)
    return name


# --------------------------- ZIP + extraction ---------------------------


@dataclass
class ZipContext:
    is_zip: bool
    zf: Optional[zipfile.ZipFile]
    tmpdir: Optional[str]


def open_input_container(input_path: str) -> ZipContext:
    """Open input as ZIP (import with files) or JSON (data only). Input must be .zip or .json."""
    path_lower = input_path.lower()
    if path_lower.endswith(".json"):
        if not os.path.isfile(input_path):
            print(f"ERROR: JSON file not found: {input_path}", file=sys.stderr)
            sys.exit(2)
        return ZipContext(False, None, None)
    if path_lower.endswith(".zip") or zipfile.is_zipfile(input_path):
        zf = zipfile.ZipFile(input_path, "r")
        if "export.json" not in zf.namelist():
            print("ERROR: ZIP missing export.json", file=sys.stderr)
            sys.exit(2)
        tmpdir = tempfile.mkdtemp(prefix="keeper_export_")
        return ZipContext(True, zf, tmpdir)
    print(
        "ERROR: Input must be a .zip (export with files) or .json (data only, no attachments).",
        file=sys.stderr,
    )
    sys.exit(2)


def read_export_json(
    input_path: str, zc: ZipContext
) -> Tuple[List[SharedFolder], List[Record]]:
    if zc.is_zip:
        assert zc.zf is not None
        with zc.zf.open("export.json") as f:
            data = json.loads(f.read().decode("utf-8"))
        json_path = os.path.join(zc.tmpdir or "", "export.json")
        with open(json_path, "w", encoding="utf-8") as out:
            json.dump(data, out)
        return load_keeper_json(json_path)
    return load_keeper_json(input_path)


def extract_and_name_attachments(zc: ZipContext, rec: Record) -> List[Tuple[str, str]]:
    if not zc.is_zip or not rec.attachments:
        return []
    assert zc.zf is not None and zc.tmpdir is not None

    results: List[Tuple[str, str]] = []
    for att in rec.attachments:
        uid = att.file_uid
        if not uid:
            continue
        blob_path = f"files/{uid}"
        if blob_path not in zc.zf.namelist():
            print(f"WARN: attachment blob missing in ZIP: {blob_path}", file=sys.stderr)
            continue
        display = att.name or uid
        base, ext = os.path.splitext(display)
        if not ext:
            guess = _ext_from_mime(att.mime)
            if guess:
                ext = guess
        out_name = base + ext
        out_path = os.path.join(zc.tmpdir, out_name)
        with zc.zf.open(blob_path) as src, open(out_path, "wb") as dst:
            dst.write(src.read())
        results.append((out_name, out_path))
    return results


# --------------------------- Build ItemCreateParams (for bulk) ---------------------------


BULK_CREATE_MAX = 100
"""Maximum items per client.items.create_all() call."""


def _chunked[T](items: List[T], size: int) -> List[List[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_login_params(
    vault_id: str,
    *,
    title: str,
    username: Optional[str],
    password: Optional[str],
    url: Optional[str],
    notes: Optional[str],
    otpauth: Optional[str],
    attachments: List[Tuple[str, str]],
) -> ItemCreateParams:
    fields: List[ItemField] = []
    if username is not None:
        fields.append(
            ItemField(
                id="username",
                value=username,
                title="Username",
                fieldType=ItemFieldType.TEXT,
            )
        )
    if password is not None:
        fields.append(
            ItemField(
                id="password",
                value=password,
                title="Password",
                fieldType=ItemFieldType.CONCEALED,
            )
        )

    sections: List[ItemSection] = []
    if otpauth:
        sections.append(ItemSection(id="sec-otp", title="Two-Factor"))
        fields.append(
            ItemField(
                id="otp",
                title="OTP",
                fieldType=ItemFieldType.TOTP,
                value=otpauth,
                section_id="sec-otp",
            )
        )

    files: List[FileCreateParams] = []
    if attachments:
        sections.append(ItemSection(id="files", title="Files"))
        for display_name, path in attachments:
            data = Path(path).read_bytes()
            files.append(
                FileCreateParams(
                    name=display_name,
                    content=data,
                    sectionId="files",
                    fieldId="file",
                )
            )

    websites: List[Website] = []
    if url:
        websites.append(
            Website(
                url=url,
                label="site",
                autofill_behavior=AutofillBehavior.ANYWHEREONWEBSITE,
            )
        )

    return ItemCreateParams(
        title=title,
        category=ItemCategory.LOGIN,
        vault_id=vault_id,
        fields=fields or None,
        sections=sections or None,
        notes=notes or None,
        websites=websites or None,
        files=files or None,
    )


def _build_secure_note_params(
    vault_id: str,
    *,
    title: str,
    notes: Optional[str],
    attachments: List[Tuple[str, str]],
) -> ItemCreateParams:
    sections: List[ItemSection] = []
    files: List[FileCreateParams] = []
    if attachments:
        sections.append(ItemSection(id="files", title="Files"))
        for display_name, path in attachments:
            data = Path(path).read_bytes()
            files.append(
                FileCreateParams(
                    name=display_name,
                    content=data,
                    sectionId="files",
                    fieldId="file",
                )
            )

    return ItemCreateParams(
        title=title,
        category=ItemCategory.SECURENOTE,
        vault_id=vault_id,
        notes=notes or None,
        sections=sections or None,
        files=files or None,
    )


# --------------------------- Planner + bulk create ---------------------------


async def plan_and_apply(
    shared_folders: List[SharedFolder],
    records: List[Record],
    *,
    employee_vault: str,
    private_prefix: str,
    dry: bool,
    silent: bool,
    user_for_private: Optional[str],
    zc: ZipContext,
) -> None:
    client = await _get_client()

    # Compute shared and private vault names
    shared_vault_map: Dict[str, str] = {}
    for sf in shared_folders:
        vault_name = normalize_path_to_name(sf.path)
        shared_vault_map[sf.path] = vault_name

    private_vault_map: Dict[str, str] = {}
    non_shared_folders = set()
    for r in records:
        for f in r.folders:
            non_shared_folders.add(f)
    for folder in sorted(non_shared_folders):
        vault_name = f"{private_prefix}{normalize_path_to_name(folder)}"
        private_vault_map[folder] = vault_name

    # All vault names we'll use (including those discovered from records)
    vault_names_used: Set[str] = {employee_vault}
    for rec in records:
        for sf in rec.shared_folders:
            if sf in shared_vault_map:
                vault_names_used.add(shared_vault_map[sf])
            else:
                name = normalize_path_to_name(sf)
                shared_vault_map[sf] = name
                vault_names_used.add(name)
        for f in rec.folders:
            if f in private_vault_map:
                vault_names_used.add(private_vault_map[f])
            else:
                name = f"{private_prefix}{normalize_path_to_name(f)}"
                private_vault_map[f] = name
                vault_names_used.add(name)

    if not silent:
        print(
            f"Using {len(vault_names_used)} vault(s) for import: {', '.join(sorted(vault_names_used))}"
        )

    # Ensure every vault exists (create via CLI if missing)
    if not dry and not _op_exists():
        print(
            "ERROR: 'op' CLI not found in PATH. Required for creating missing vaults.",
            file=sys.stderr,
        )
        sys.exit(1)
    name_to_id, vault_titles = await _vault_name_to_id_map(client)
    need_create: List[str] = []
    for v in vault_names_used:
        if v not in name_to_id and _normalize_vault_name(v) not in name_to_id:
            need_create.append(v)
    if need_create and not silent:
        print(f"Vault(s) to create: {', '.join(sorted(need_create))}")
    for v in need_create:
        _ensure_vault(v, dry=dry, silent=silent)
    if not dry and need_create:
        name_to_id, vault_titles = await _vault_name_to_id_map(client)
        if not silent:
            print(
                f"Vaults after create ({len(vault_titles)}): {', '.join(vault_titles)}"
            )

    # Resolve vault names to IDs (for SDK group grants and item creation)
    resolved: Dict[str, str] = {}
    for v in vault_names_used:
        resolved[v] = _resolve_vault_id(name_to_id, v)

    # Apply permission mapping: groups via SDK, users via CLI
    for sf in shared_folders:
        vault_name = shared_vault_map[sf.path]
        vault_id = resolved[vault_name]
        for perm in sf.permissions:
            if not dry and not _subject_exists(perm.name, perm.is_group):
                if not silent:
                    print(
                        f"WARN: {'Group' if perm.is_group else 'User'} {perm.name!r} not found; skipping permission on {vault_name!r}",
                        file=sys.stderr,
                    )
                continue
            if perm.is_group:
                group_id = None if dry else _get_group_id_by_name(perm.name)
                if group_id or dry:
                    await _grant_group_permissions_sdk(
                        client,
                        vault_id,
                        group_id if group_id else perm.name,  # name only for dry-run message
                        manage_users=perm.manage_users,
                        manage_records=perm.manage_records,
                        dry=dry,
                        silent=silent,
                    )
                elif not dry:
                    print(
                        f"WARN: Group {perm.name!r} not found; skipping permission on {vault_name!r}",
                        file=sys.stderr,
                    )
            else:
                _grant_user_permissions(
                    vault_name,
                    perm.name,
                    manage_users=perm.manage_users,
                    manage_records=perm.manage_records,
                    dry=dry,
                    silent=silent,
                )

    for vault_name in set(private_vault_map.values()):
        if user_for_private:
            _grant_user_permissions(
                vault_name,
                user_for_private,
                manage_users=False,
                manage_records=True,
                dry=dry,
                silent=silent,
            )

    if dry:
        for rec in records:
            destinations: List[str] = []
            for sf in rec.shared_folders:
                destinations.append(
                    shared_vault_map.get(sf, normalize_path_to_name(sf))
                )
            for f in rec.folders:
                destinations.append(
                    private_vault_map.get(
                        f, f"{private_prefix}{normalize_path_to_name(f)}"
                    )
                )
            if not destinations:
                destinations = [employee_vault]
            att_list = extract_and_name_attachments(zc, rec)
            for vault_name in destinations:
                kind = "LOGIN" if rec.category == "Login" else "NOTE"
                names = [n for n, _ in att_list]
                msg = f"DRY-RUN: {kind} '{rec.title}' → vault '{vault_name}'"
                if rec.category == "Login" and rec.otpauth:
                    msg += " with TOTP"
                if names:
                    msg += f" with files {names}"
                print(msg)
        return

    # Build (vault_id -> list of ItemCreateParams) for bulk create
    batches: Dict[str, List[ItemCreateParams]] = defaultdict(list)

    for rec in records:
        destinations: List[str] = []
        for sf in rec.shared_folders:
            if sf in shared_vault_map:
                destinations.append(shared_vault_map[sf])
            else:
                name = normalize_path_to_name(sf)
                shared_vault_map[sf] = name
                destinations.append(name)
        for f in rec.folders:
            if f in private_vault_map:
                destinations.append(private_vault_map[f])
            else:
                name = f"{private_prefix}{normalize_path_to_name(f)}"
                private_vault_map[f] = name
                destinations.append(name)
        if not destinations:
            destinations = [employee_vault]

        att_list = extract_and_name_attachments(zc, rec)

        for vault_name in destinations:
            vault_id = resolved[vault_name]
            if rec.category == "Login":
                params = _build_login_params(
                    vault_id,
                    title=rec.title,
                    username=rec.login,
                    password=rec.password,
                    url=rec.login_url,
                    notes=rec.notes,
                    otpauth=rec.otpauth,
                    attachments=att_list,
                )
            else:
                notes = rec.notes or ""
                if rec.login_url:
                    notes = (notes + ("\n" if notes else "")) + f"URL: {rec.login_url}"
                params = _build_secure_note_params(
                    vault_id,
                    title=rec.title,
                    notes=notes,
                    attachments=att_list,
                )
            batches[vault_id].append(params)

    # Bulk create per vault, in chunks of BULK_CREATE_MAX
    id_to_name = {vid: name for name, vid in resolved.items()}
    for vault_id, params_list in batches.items():
        if not params_list:
            continue
        vault_title = id_to_name.get(vault_id, vault_id)
        if not silent:
            print(f"Creating {len(params_list)} item(s) in vault '{vault_title}'...")
        total_ok = 0
        for chunk in _chunked(params_list, BULK_CREATE_MAX):
            try:
                resp: ItemsUpdateAllResponse = await client.items.create_all(
                    vault_id, chunk
                )
            except Exception as e:
                print(
                    f"ERROR bulk create in vault {vault_title}: {e}",
                    file=sys.stderr,
                )
                continue

            for i, ir in enumerate(resp.individual_responses):
                if ir.error is not None:
                    title = chunk[i].title if i < len(chunk) else "?"
                    print(
                        f"ERROR creating item '{title}' in vault: {ir.error}",
                        file=sys.stderr,
                    )
                else:
                    total_ok += 1

        if not silent:
            print(
                f"✔ Bulk created {total_ok}/{len(params_list)} items in vault '{vault_title}'"
            )


# --------------------------- Entrypoint ---------------------------


async def main() -> None:
    ap = argparse.ArgumentParser(
        description="Keeper → 1Password migration with attachments (SDK-only bulk create)"
    )
    ap.add_argument(
        "--input",
        required=True,
        help="Path to .zip (export with files) or .json (data only, no attachments)",
    )
    ap.add_argument(
        "--employee-vault",
        required=True,
        help="Name of the Employee/Private vault for items without folders",
    )
    ap.add_argument(
        "--private-prefix",
        default="Private - ",
        help="Prefix for private vault names (default: 'Private - ')",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Don't create; print planned actions"
    )
    ap.add_argument(
        "--silent", action="store_true", help="Do not print progress messages"
    )
    ap.add_argument(
        "--user-for-private",
        help="User (e.g. email) to grant access to private vaults (allow_editing + allow_viewing)",
    )

    args = ap.parse_args()

    zc = open_input_container(args.input)
    if not zc.is_zip and not args.silent:
        print("Input is JSON; importing without attachments.")
    try:
        shared, records = read_export_json(args.input, zc)
    except Exception as e:
        print(f"Failed to parse input: {e}", file=sys.stderr)
        sys.exit(2)

    if not args.silent:
        print(
            f"Loaded {len(shared)} shared folders and {len(records)} records from {os.path.basename(args.input)}"
        )

    await plan_and_apply(
        shared,
        records,
        employee_vault=args.employee_vault,
        private_prefix=args.private_prefix,
        dry=args.dry_run,
        silent=args.silent,
        user_for_private=args.user_for_private,
        zc=zc,
    )


if __name__ == "__main__":
    asyncio.run(main())
