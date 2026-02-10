#!/usr/bin/env python3
"""
Keeper→1Password migration helper (ZIP with files) — bulk create via beta SDK

Same behavior as import-with-files.py but uses the 1Password beta Python SDK's
Items.create_all to create items in batch per vault (fewer round-trips).

- Accepts an input **ZIP** with `export.json` and `files/` (or bare keeper JSON).
- Renames attachment blobs from UID to display name; attaches files to items.
- Creates shared/private vaults and grants permissions via `op` CLI.
- Builds all item params, groups by vault, and calls client.items.create_all()
  for each vault.

Requires: 1Password CLI v2 (for vault/permission setup), OP_SERVICE_ACCOUNT_TOKEN,
          onepassword-sdk (beta with create_all, e.g. 0.4.0b2).

Usage
-----
python import-with-files-bulk.py \\
  --input /path/to/export-files.zip \\
  --employee-vault "Keeper Import" \\
  [--private-prefix "Private - "] \\
  [--dry-run] [--silent] [--user-for-private you@example.com]
"""
from __future__ import annotations

import argparse
import asyncio
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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from onepassword.client import Client
from onepassword import (
    AutofillBehavior,
    FileCreateParams,
    ItemCategory,
    ItemCreateParams,
    ItemField,
    ItemFieldType,
    ItemSection,
    ItemsUpdateAllResponse,
    Website,
)

# --- Session bootstrap ---------------------------------------------------------


async def _get_client() -> Client:
    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
    if not token:
        raise RuntimeError("OP_SERVICE_ACCOUNT_TOKEN is not set")
    return await Client.authenticate(
        auth=token,
        integration_name="Importer",
        integration_version="v1",
    )


def _resolve_vault_id_via_cli(vault_name: str) -> str:
    """Resolve vault name to vault ID using op CLI (SDK often returns [Encrypted] for titles)."""
    proc = run(["op", "vault", "get", vault_name, "--format", "json"])
    if proc.returncode != 0:
        err = proc.stderr.decode().strip() or proc.stdout.decode().strip()
        raise ValueError(f"Vault not found: {vault_name!r}. {err}")
    data = json.loads(proc.stdout.decode())
    vid = data.get("id")
    if not vid:
        raise ValueError(f"Vault not found: {vault_name!r} (no id in op output)")
    return vid


async def _resolve_vault_id(client: Client, vault: str) -> str:
    """Resolve vault name to vault ID. Uses op CLI so names work when SDK returns [Encrypted]."""
    return _resolve_vault_id_via_cli(vault)


# --------------------------- CLI helpers ---------------------------


def run(
    cmd: List[str], *, input_bytes: Optional[bytes] = None, check: bool = False
) -> subprocess.CompletedProcess:
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


# --------------------------- 1Password vault/permission (CLI) ---------------------------


def ensure_vault(vault_name: str, *, dry: bool, silent: bool) -> None:
    proc = run(["op", "vault", "get", vault_name, "--format", "json"])
    if proc.returncode == 0:
        if not silent:
            print(f"✔ Vault exists: {vault_name}")
        return
    if dry:
        print(f"DRY-RUN: would create vault: {vault_name}")
        return
    proc2 = run(["op", "vault", "create", vault_name, "--format", "json"])
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
        stderr = proc.stderr.decode().strip()
        print(f"WARN granting {subject} on {vault}: {stderr}", file=sys.stderr)


# --------------------------- ZIP + extraction ---------------------------


@dataclass
class ZipContext:
    is_zip: bool
    zf: Optional[zipfile.ZipFile]
    tmpdir: Optional[str]


def open_input_container(input_path: str) -> ZipContext:
    if zipfile.is_zipfile(input_path):
        zf = zipfile.ZipFile(input_path, "r")
        if "export.json" not in zf.namelist():
            print("ERROR: ZIP missing export.json", file=sys.stderr)
            sys.exit(2)
        tmpdir = tempfile.mkdtemp(prefix="keeper_export_")
        return ZipContext(True, zf, tmpdir)
    return ZipContext(False, None, None)


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

BULK_CREATE_MAX = 10
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
    if not op_exists():
        print("ERROR: 'op' (1Password CLI) not found in PATH.", file=sys.stderr)
        sys.exit(1)

    client = await _get_client()

    shared_vault_map: Dict[str, str] = {}
    for sf in shared_folders:
        vault_name = normalize_path_to_name(sf.path)
        shared_vault_map[sf.path] = vault_name
        ensure_vault(vault_name, dry=dry, silent=silent)
        for perm in sf.permissions:
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

    private_vault_map: Dict[str, str] = {}
    non_shared_folders = set()
    for r in records:
        for f in r.folders:
            non_shared_folders.add(f)
    for folder in sorted(non_shared_folders):
        vault_name = f"{private_prefix}{normalize_path_to_name(folder)}"
        private_vault_map[folder] = vault_name
        ensure_vault(vault_name, dry=dry, silent=silent)
        if user_for_private:
            grant_permissions(
                vault_name,
                user_for_private,
                is_group=False,
                manage_users=False,
                manage_records=True,
                dry=dry,
            )

    ensure_vault(employee_vault, dry=dry, silent=silent)

    # Collect all vault names we'll use and resolve to IDs once
    vault_names_used: Set[str] = {employee_vault}
    for rec in records:
        for sf in rec.shared_folders:
            if sf in shared_vault_map:
                vault_names_used.add(shared_vault_map[sf])
            else:
                name = normalize_path_to_name(sf)
                shared_vault_map[sf] = name
                ensure_vault(name, dry=dry, silent=silent)
                vault_names_used.add(name)
        for f in rec.folders:
            if f in private_vault_map:
                vault_names_used.add(private_vault_map[f])
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
                vault_names_used.add(name)

    if dry:
        # Dry-run: print what would be created per vault
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
            for v in destinations:
                kind = "LOGIN" if rec.category == "Login" else "NOTE"
                names = [n for n, _ in att_list]
                msg = f"DRY-RUN: {kind} '{rec.title}' → vault '{v}'"
                if rec.category == "Login" and rec.otpauth:
                    msg += " with TOTP"
                if names:
                    msg += f" with files {names}"
                print(msg)
        return

    name_to_id: Dict[str, str] = {}
    for v in vault_names_used:
        name_to_id[v] = await _resolve_vault_id(client, v)

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
            vault_id = name_to_id[vault_name]
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
    for vault_id, params_list in batches.items():
        if not params_list:
            continue
        vault_title = next(
            (n for n, vid in name_to_id.items() if vid == vault_id), vault_id
        )
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
        description="Keeper → 1Password migration with attachments (bulk create via beta SDK)"
    )
    ap.add_argument(
        "--input", required=True, help="Path to export-files.zip or keeper.json"
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
        help="Email of user to grant access to private vaults",
    )

    args = ap.parse_args()

    zc = open_input_container(args.input)
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
