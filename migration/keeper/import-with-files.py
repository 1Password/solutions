#!/usr/bin/env python3
"""
Keeper→1Password migration helper (ZIP with files)

Enhancements over the original:
- Accepts an input **ZIP** created like `export-files.zip` containing `export.json` and a `files/` folder of binary blobs named by UID.
- Renames file blobs from UID to the display name from `attachments[].name` (preserves extension; falls back to MIME if needed).
- Attaches files to created 1Password items using `file` custom-field assignments during creation, so files are stored on the item.

Notes
-----
- Requires 1Password CLI v2, signed-in session or service account token.
- Attachments are added using assignment statements per docs
  (see: Create items → Attach a file). The field is the file name you want
  shown in 1Password; the value is the local file path.
- If a record has multiple placements (shared + private folders), files are
  attached on every duplicated item, matching the original script's duplication
  semantics for items in multiple folders.

Usage
-----
python keeper_to_1password_with_attachments.py \
  --input /path/to/export-files.zip \
  --employee-vault "Keeper Import" \
  [--private-prefix "Private - "] \
  [--dry-run] [--silent] [--user-for-private you@example.com]

You can still pass a bare Keeper JSON (`--input keeper.json`); attachments are
only supported when a ZIP with a `files/` directory is provided.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    category: str  # "Login" or "Secure Note"
    attachments: List[Attachment]


# --------------------------- Parsing ---------------------------


def _escape_field_name(name: str) -> str:
    """Escape characters that have meaning in assignment statements.
    Docs: use backslash to escape periods, equal signs, and backslashes.
    """
    return (
        name.replace("\\", r"\\\\")
        .replace("=", r"\=")
        .replace(".", r"\.")
    )


def _ext_from_mime(mime: Optional[str]) -> Optional[str]:
    if not mime:
        return None
    ext = mimetypes.guess_extension(mime)
    # Normalize some uncommon or None cases
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
        # Attachments in Keeper export-files.json
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


# --------------------------- Name helpers ---------------------------


def normalize_path_to_name(path: str) -> str:
    name = path.replace("\\", "/").strip()
    name = re.sub(r"\s+", " ", name)
    return name


# --------------------------- 1Password wrappers ---------------------------


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
    item = json.loads(json.dumps(tpl))
    item["title"] = title

    def set_field(fid: str, value: Optional[str]):
        if value is None:
            return
        for f in item.get("fields", []) or []:
            if f.get("id") == fid:
                f["value"] = value
                return
        item.setdefault("fields", []).append({"id": fid, "type": "STRING", "value": value})

    set_field("username", username)
    if password is not None:
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


# --------------------------- ZIP + extraction helpers ---------------------------


@dataclass
class ZipContext:
    is_zip: bool
    zf: Optional[zipfile.ZipFile]
    tmpdir: Optional[str]


def open_input_container(input_path: str) -> ZipContext:
    if zipfile.is_zipfile(input_path):
        zf = zipfile.ZipFile(input_path, "r")
        # Validate contents
        if "export.json" not in zf.namelist():
            print("ERROR: ZIP missing export.json", file=sys.stderr)
            sys.exit(2)
        tmpdir = tempfile.mkdtemp(prefix="keeper_export_")
        return ZipContext(True, zf, tmpdir)
    else:
        return ZipContext(False, None, None)


def read_export_json(input_path: str, zc: ZipContext) -> Tuple[List[SharedFolder], List[Record]]:
    if zc.is_zip:
        assert zc.zf is not None
        with zc.zf.open("export.json") as f:
            data = json.loads(f.read().decode("utf-8"))
        json_path = os.path.join(zc.tmpdir or "", "export.json")
        with open(json_path, "w", encoding="utf-8") as out:
            json.dump(data, out)
        return load_keeper_json(json_path)
    else:
        return load_keeper_json(input_path)


def extract_and_name_attachments(zc: ZipContext, rec: Record) -> List[Tuple[str, str]]:
    """Return list of (display_name, local_path) for this record's attachments.
    For ZIP inputs only; returns [] otherwise.
    """
    if not zc.is_zip or not rec.attachments:
        return []
    assert zc.zf is not None and zc.tmpdir is not None

    results: List[Tuple[str, str]] = []
    for att in rec.attachments:
        uid = att.file_uid
        if not uid:
            continue
        # Try to read files/<uid>
        blob_path = f"files/{uid}"
        if blob_path not in zc.zf.namelist():
            print(f"WARN: attachment blob missing in ZIP: {blob_path}", file=sys.stderr)
            continue
        # Determine filename
        display = att.name or uid
        base, ext = os.path.splitext(display)
        if not ext:
            guess = _ext_from_mime(att.mime)
            if guess:
                ext = guess
        out_name = base + ext
        # Write to temp dir with the display name
        out_path = os.path.join(zc.tmpdir, out_name)
        with zc.zf.open(blob_path) as src, open(out_path, "wb") as dst:
            dst.write(src.read())
        results.append((out_name, out_path))
    return results


# --------------------------- Item creation ---------------------------


def create_login_item(
    vault: str,
    *,
    title: str,
    username: Optional[str],
    password: Optional[str],
    url: Optional[str],
    notes: Optional[str],
    otpauth: Optional[str],
    attachments: List[Tuple[str, str]],  # (display_name, path)
    dry: bool,
    silent: bool,
    tpl_cache: Dict[str, Any],
) -> None:
    if dry:
        attach_names = [n for n, _ in attachments]
        print(
            f"DRY-RUN: LOGIN '{title}' → vault '{vault}'"
            + (" with TOTP" if otpauth else "")
            + (f" with files {attach_names}" if attach_names else "")
        )
        return

    tpl = tpl_cache.setdefault("login", get_login_template_json())
    item_json = fill_login_template(
        tpl, title=title, username=username, password=password, url=url, notes=notes
    )
    payload = json.dumps(item_json).encode()

    cmd = ["op", "item", "create", "-", "--vault", vault]

    # Attach OTP via assignment
    if otpauth:
        cmd.append(f"otp[otp]={otpauth}")

    # Attach files via assignment statements: <name>[file]=/path
    for disp, p in attachments:
        field = _escape_field_name(disp)
        cmd.append(f"{field}[file]={p}")

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
    vault: str,
    *,
    title: str,
    notes: Optional[str],
    attachments: List[Tuple[str, str]],
    dry: bool,
    silent: bool,
) -> None:
    if dry:
        attach_names = [n for n, _ in attachments]
        print(
            f"DRY-RUN: NOTE '{title}' → vault '{vault}'"
            + (f" with files {attach_names}" if attach_names else "")
        )
        return

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

    for disp, p in attachments:
        field = _escape_field_name(disp)
        cmd.append(f"{field}[file]={p}")

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
    zc: ZipContext,
) -> None:
    if not op_exists():
        print("ERROR: 'op' (1Password CLI) not found in PATH.", file=sys.stderr)
        sys.exit(1)

    # 1) Create shared vaults and grant perms
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

    # 2) Create private vaults
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

    # 3) Ensure employee vault exists
    ensure_vault(employee_vault, dry=dry, silent=silent)

    # 4) Create items
    tpl_cache: Dict[str, Any] = {}
    for rec in records:
        destinations: List[str] = []
        for sf in rec.shared_folders:
            if sf in shared_vault_map:
                destinations.append(shared_vault_map[sf])
            else:
                name = normalize_path_to_name(sf)
                shared_vault_map[sf] = name
                ensure_vault(name, dry=dry, silent=silent)
                destinations.append(name)
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
        if not destinations:
            destinations = [employee_vault]

        # Prepare attachments if ZIP
        att_list = extract_and_name_attachments(zc, rec)

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
                    attachments=att_list,
                    dry=dry,
                    silent=silent,
                    tpl_cache=tpl_cache,
                )
            else:
                notes = rec.notes or ""
                if rec.login_url:
                    notes = (notes + ("\n" if notes else "")) + f"URL: {rec.login_url}"
                create_secure_note(
                    vault,
                    title=rec.title,
                    notes=notes,
                    attachments=att_list,
                    dry=dry,
                    silent=silent,
                )


# --------------------------- Entrypoint ---------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Keeper → 1Password migration helper with attachments from ZIP"
    )
    ap.add_argument("--input", required=True, help="Path to export-files.zip or keeper.json")
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

    # Open container and parse JSON
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

    # Apply plan
    plan_and_apply(
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
    main()
