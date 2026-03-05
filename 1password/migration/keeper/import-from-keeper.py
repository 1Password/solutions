#!/usr/bin/env python3
"""
Keeper→1Password migration helper (ZIP with files) — SDK bulk create

Uses the 1Password Python SDK for items and vault listing:
- Items.create_all for bulk item creation (max 100 per call).
- Vaults.list(decrypt_details=True) to resolve vault names to IDs.
- Vaults.create() to create missing vaults.
- Vaults.grant_group_permissions for group vault access (SDK).

User vault permissions are applied via the `op` CLI (`op vault user grant`).
Group vault permissions are applied via the SDK. The `op` CLI must be in PATH
for user grants to be applied automatically.

Accepts three input formats:
  - A **.zip** file with `export.json` and `files/` (import with attachments).
  - A **.json** file (Keeper export data only; no attachments).
  - A **.kdbx** file — Keeper KeePass export (credentials + attachments ≤1MB each).
                       You will be prompted for the KeePass password at runtime.
                       NOTE: KDBX does not contain shared folder permission data.
                       Use JSON for permissions, KDBX for attachments.

For ZIP: attaches files to items using their original Keeper display names.
Permission mapping: Keeper shared_folder permissions → 1Password vault access
  (manage_users → allow_managing, manage_records → allow_editing, else allow_viewing).

Folder → Vault mapping:
  Without --collapse-folders:
    - Top-level folder items → vault named after the folder, tagged with folder name.
    - Sub-folder items       → vault named after the child folder only,
                               tagged with "Parent\\Child".
  With --collapse-folders:
    - All items go into the parent vault.
    - Top-level items tagged with parent name.
    - Sub-folder items tagged with "Parent\\Child".

Resumability: if the import is interrupted (e.g. by a rate limit / 429), a
state file is written next to the input file. Re-running the same command
will resume from where it left off — completed items are skipped. On full
success the state file is deleted automatically.

Requires: OP_SERVICE_ACCOUNT_TOKEN, onepassword-sdk, and `op` CLI (for user vault grants).
pykeepass is required for KDBX input and is auto-installed if needed.
If a requirements.txt exists next to this script, missing packages are
installed automatically into a local .venv-1pw virtual environment.

Usage
-----
# JSON (credentials + folder structure, no attachments):
python import-from-keeper.py \\
  --input keeper-export.json \\
  --employee-vault "Keeper Import" \\
  [--private-prefix "Private - "] \\
  [--collapse-folders] [--dry-run] [--silent]

# ZIP (credentials + folder structure + attachments):
python import-from-keeper.py \\
  --input keeper-export.zip \\
  --employee-vault "Keeper Import" \\
  [--collapse-folders] [--dry-run] [--silent]

# KDBX (credentials + attachments, no shared folder permissions):
python import-from-keeper.py \\
  --input keeper-export.kdbx \\
  --employee-vault "Keeper Import" \\
  [--collapse-folders] [--dry-run] [--silent]
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import getpass
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Auto-install: if onepassword SDK is missing, create a venv next to this
# script, install requirements.txt (or just onepassword-sdk), and re-exec.
# ---------------------------------------------------------------------------

try:
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
        VaultCreateParams,
        VaultListParams,
        Website,
    )
except ImportError:
    import subprocess as _sp
    import venv as _venv

    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _venv_dir = os.path.join(_script_dir, ".venv-1pw")
    _venv_python = os.path.join(_venv_dir, "bin", "python")

    # Guard: if we're already inside the venv and still failing, bail out
    if sys.executable == _venv_python:
        print(
            "ERROR: onepassword-sdk failed to import even inside the venv.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create the venv if it doesn't exist yet
    if not os.path.isfile(_venv_python):
        print(f"Creating virtual environment at {_venv_dir}...")
        _venv.create(_venv_dir, with_pip=True)

    # Install from requirements.txt if present, otherwise both packages
    _req_file = os.path.join(_script_dir, "requirements.txt")
    if os.path.isfile(_req_file):
        print(f"Installing packages from {_req_file}...")
        _sp.check_call(
            [_venv_python, "-m", "pip", "install", "--quiet", "-r", _req_file]
        )
    else:
        print("Installing onepassword-sdk and pykeepass...")
        _sp.check_call(
            [_venv_python, "-m", "pip", "install", "--quiet", "onepassword-sdk", "pykeepass"]
        )

    # Re-launch this script inside the venv with all original arguments
    print("Restarting inside virtual environment...\n")
    os.execv(_venv_python, [_venv_python] + sys.argv)


# ---------------------------------------------------------------------------
# pykeepass check: runs after SDK import succeeds. Catches the case where the
# venv already existed before KDBX support was added, so pykeepass was never
# installed into it. Auto-installs and re-execs so the import succeeds.
# ---------------------------------------------------------------------------
try:
    import pykeepass as _pykeepass_check
except ImportError:
    import subprocess as _sp2

    _script_dir2 = os.path.dirname(os.path.abspath(__file__))
    _venv_python2 = os.path.join(_script_dir2, ".venv-1pw", "bin", "python")

    if os.path.isfile(_venv_python2):
        # venv exists — install pykeepass into it and re-exec inside the venv
        print("Installing pykeepass into existing virtual environment...")
        _sp2.check_call([_venv_python2, "-m", "pip", "install", "--quiet", "pykeepass"])
        print("Restarting...\n")
        os.execv(_venv_python2, [_venv_python2] + sys.argv)
    else:
        # No venv — install into current environment and re-exec
        print("Installing pykeepass...")
        _sp2.check_call([sys.executable, "-m", "pip", "install", "--quiet", "pykeepass"])
        os.execv(sys.executable, [sys.executable] + sys.argv)


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
    seen_titles: Set[str] = set()
    for v in vaults:
        name_to_id[v.title] = v.id
        seen_titles.add(v.title)
        normalized = _normalize_vault_name(v.title)
        if normalized != v.title:
            name_to_id[normalized] = v.id
    return name_to_id, sorted(seen_titles)


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


async def _ensure_vault(
    client: Client,
    vault_name: str,
    name_to_id: Dict[str, str],
    *,
    dry: bool,
    silent: bool,
) -> Optional[str]:
    """Create vault via SDK if it doesn't exist. Returns vault ID (None for dry-run new vaults)."""
    for key in (vault_name, _normalize_vault_name(vault_name)):
        if key in name_to_id:
            if not silent:
                print(f"✔ Vault exists: {vault_name}")
            return name_to_id[key]

    if dry:
        print(f"DRY-RUN: would create vault: {vault_name}")
        return None

    try:
        created = await client.vaults.create(VaultCreateParams(title=vault_name))
    except Exception as e:
        print(f"ERROR creating vault {vault_name!r}: {e}", file=sys.stderr)
        sys.exit(2)

    if not silent:
        print(f"➕ Created vault: {vault_name} (id={created.id})")

    # Update map so subsequent lookups work without re-listing
    name_to_id[vault_name] = created.id
    normalized = _normalize_vault_name(vault_name)
    if normalized != vault_name:
        name_to_id[normalized] = created.id

    return created.id


# Permission masks for SDK (1Password Business granular permissions)
_PERM_VIEWING = READ_ITEMS | REVEAL_ITEM_PASSWORD | UPDATE_ITEM_HISTORY
_PERM_EDITING = _PERM_VIEWING | (
    CREATE_ITEMS
    | UPDATE_ITEMS
    | ARCHIVE_ITEMS
    | DELETE_ITEMS
    | IMPORT_ITEMS
    | EXPORT_ITEMS
    | SEND_ITEMS
    | PRINT_ITEMS
)
_PERM_MANAGING = _PERM_EDITING | MANAGE_VAULT


def _perms_list(manage_users: bool, manage_records: bool) -> List[str]:
    """CLI permission names: allow_viewing, allow_editing, allow_managing."""
    perms = ["allow_viewing"]
    if manage_records:
        perms.append("allow_editing")
    if manage_users:
        perms.append("allow_managing")
    return perms


def _run_op(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def _op_exists() -> bool:
    return which("op") is not None


def _grant_user_permissions(
    vault_name: str,
    user_name: str,
    *,
    manage_users: bool,
    manage_records: bool,
    dry: bool,
    silent: bool,
) -> None:
    """Grant vault permissions to a user via the op CLI."""
    perms = _perms_list(manage_users, manage_records)
    if dry:
        if not silent:
            print(f"DRY-RUN: would grant user {user_name!r} on {vault_name!r}: {perms}")
        return
    if not _op_exists():
        print(
            f"WARN: 'op' CLI not found — cannot grant user {user_name!r} on {vault_name!r}. "
            f"Run manually: op vault user grant --vault {vault_name!r} --user {user_name!r} "
            f"--permissions {','.join(perms)}",
            file=sys.stderr,
        )
        return
    cmd = [
        "op", "vault", "user", "grant",
        "--no-input",
        "--vault", vault_name,
        "--user", user_name,
        "--permissions", ",".join(perms),
    ]
    proc = _run_op(cmd)
    if proc.returncode != 0:
        print(
            f"WARN granting user {user_name!r} on {vault_name!r}: {proc.stderr.strip()}",
            file=sys.stderr,
        )
    elif not silent:
        print(f"✔ Granted user {user_name!r} on vault {vault_name!r}: {perms}")


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
            perms_desc = (
                "allow_managing"
                if manage_users
                else ("allow_editing" if manage_records else "allow_viewing")
            )
            print(f"DRY-RUN: would grant group {group_id!r} on vault: {perms_desc}")
        return
    try:
        await client.vaults.grant_group_permissions(
            vault_id,
            [GroupAccess(group_id=group_id, permissions=perm_int)],
        )
    except Exception as e:
        print(f"WARN granting group on vault {vault_id!r}: {e}", file=sys.stderr)


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
class InMemoryAttachment:
    """An attachment held entirely in memory — never touches disk."""
    name: str
    content: bytes


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
    sub_folders: List[str]
    category: str
    attachments: List[InMemoryAttachment] = field(default_factory=list)


# --------------------------- Resumable state file ---------------------------


def _item_fingerprint(vault_id: str, rec: Record) -> str:
    """Deterministic hash for a (vault, record) pair.

    Uses vault_id + title + category + login + password so that the same
    record targeted at the same vault always produces the same fingerprint,
    even across runs. Attachment names are included so that two records
    with the same title but different files are distinguished.
    """
    parts = [
        vault_id,
        rec.title,
        rec.category,
        rec.login or "",
        rec.password or "",
        rec.login_url or "",
        rec.otpauth or "",
        ",".join(sorted(a.name for a in rec.attachments)),
    ]
    raw = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _state_file_path(input_path: str) -> str:
    """Return the path for the state file, next to the input file."""
    base = os.path.splitext(input_path)[0]
    return f"{base}.import-state.json"


def _compute_checksum(fingerprints: List[str]) -> str:
    """SHA-256 over the sorted fingerprint list — detects tampering / corruption."""
    payload = "\n".join(sorted(fingerprints)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_state(input_path: str, *, silent: bool) -> Set[str]:
    """Load completed fingerprints from the state file. Returns empty set if none."""
    path = _state_file_path(input_path)
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARN: Could not read state file {path}: {e}. Starting fresh.", file=sys.stderr)
        return set()

    fingerprints = data.get("completed", [])
    if _compute_checksum(fingerprints) != data.get("checksum", ""):
        print("WARN: State file checksum mismatch — starting fresh.", file=sys.stderr)
        return set()

    if not silent:
        print(f"📋 Resuming: {len(fingerprints)} items already completed")
    return set(fingerprints)


def save_state(input_path: str, completed: Set[str], *, silent: bool) -> None:
    """Write the state file with completed fingerprints and integrity checksum."""
    path = _state_file_path(input_path)
    fingerprints = sorted(completed)
    data = {
        "checksum": _compute_checksum(fingerprints),
        "completed": fingerprints,
        "count": len(fingerprints),
    }
    # Atomic-ish write: write to temp then rename
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)
    if not silent:
        print(f"💾 State saved: {len(fingerprints)} items completed → {path}")


def delete_state(input_path: str, *, silent: bool) -> None:
    """Remove the state file after a fully successful import."""
    path = _state_file_path(input_path)
    if os.path.isfile(path):
        os.remove(path)
        if not silent:
            print("🗑  Removed state file (import complete)")


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception indicates a 429 rate limit."""
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


# --------------------------- Parsing ---------------------------


def _ext_from_mime(mime: Optional[str]) -> Optional[str]:
    if not mime:
        return None
    ext = mimetypes.guess_extension(mime)
    if ext == ".jpe":
        ext = ".jpg"
    return ext


def load_keeper_json(path_or_data) -> Tuple[List[SharedFolder], List[Record]]:
    """Parse a Keeper JSON export (file path or pre-loaded dict) into SharedFolders and Records."""
    if isinstance(path_or_data, dict):
        data = path_or_data
    else:
        with open(path_or_data, "r", encoding="utf-8") as f:
            data = json.load(f)

    shared: List[SharedFolder] = []
    for sf in data.get("shared_folders", []):
        sf_path = sf.get("path") or ""
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
                    manage_records=bool(p.get("manage_records", defaults_manage_records)),
                )
            )
        shared.append(
            SharedFolder(sf_path, defaults_manage_users, defaults_manage_records, perms)
        )

    records: List[Record] = []
    for r in data.get("records", []):
        title = r.get("title") or "Untitled"
        login = r.get("login")
        password = r.get("password")
        login_url = r.get("login_url")

        # Read notes from top-level field first, then fall back to
        # custom_fields keys prefixed with "$note::" (used by Keeper secure notes).
        notes = r.get("notes")
        if not notes:
            for k, v in (r.get("custom_fields") or {}).items():
                if isinstance(k, str) and k.startswith("$note::") and isinstance(v, str):
                    notes = v
                    break

        # Extract TOTP — custom_fields values that look like otpauth:// URIs
        otpauth = None
        for k, v in (r.get("custom_fields") or {}).items():
            if isinstance(v, str) and v.startswith("otpauth://"):
                otpauth = v
                break

        shared_folders: List[str] = []
        sub_folders: List[str] = []   # record-level sub-folder inside a shared folder
        folders: List[str] = []
        for fldr in r.get("folders", []) or []:
            if "shared_folder" in fldr:
                shared_folders.append(str(fldr["shared_folder"]))
                # Capture the record-level sub-folder name for vault/tag routing
                if "folder" in fldr:
                    sub_folders.append(str(fldr["folder"]))
            elif "folder" in fldr:
                folders.append(str(fldr["folder"]))

        category = (
            "Login"
            if (r.get("$type") == "login" or (login and password))
            else "Secure Note"
        )

        records.append(
            Record(
                title=title,
                login=login,
                password=password,
                login_url=login_url,
                notes=notes,
                otpauth=otpauth,
                shared_folders=shared_folders,
                folders=folders,
                sub_folders=sub_folders,
                category=category,
            )
        )

    return shared, records


def normalize_path_to_name(path: str) -> str:
    name = path.replace("\\", "/").strip()
    name = re.sub(r"\s+", " ", name)
    return name


def _split_folder_path(path: str) -> Tuple[str, Optional[str]]:
    """Split 'Engineering\\DevOps' → ('Engineering', 'DevOps').
    Single-segment paths return (segment, None)."""
    normalized = path.replace("\\", "/").strip()
    parts = normalized.split("/", 1)
    parent = parts[0].strip()
    child = parts[1].strip() if len(parts) > 1 else None
    return parent, child


# --------------------------- ZIP + KDBX input ---------------------------


@dataclass
class InputContext:
    """Holds open file handles for ZIP input. No temp files are created."""
    zf: Optional[zipfile.ZipFile]
    is_kdbx: bool = False

    @property
    def is_zip(self) -> bool:
        return self.zf is not None


def open_input_container(input_path: str) -> InputContext:
    """Open input as ZIP, JSON, or KDBX. Input must be .zip, .json, or .kdbx."""
    path_lower = input_path.lower()
    if path_lower.endswith(".json"):
        if not os.path.isfile(input_path):
            print(f"ERROR: JSON file not found: {input_path}", file=sys.stderr)
            sys.exit(2)
        return InputContext(zf=None)
    if path_lower.endswith(".kdbx"):
        if not os.path.isfile(input_path):
            print(f"ERROR: KDBX file not found: {input_path}", file=sys.stderr)
            sys.exit(2)
        return InputContext(zf=None, is_kdbx=True)
    if path_lower.endswith(".zip") or zipfile.is_zipfile(input_path):
        zf = zipfile.ZipFile(input_path, "r")
        if "export.json" not in zf.namelist():
            print("ERROR: ZIP missing export.json", file=sys.stderr)
            sys.exit(2)
        return InputContext(zf=zf)
    print(
        "ERROR: Input must be a .zip (export with files), .json (data only, no attachments), or .kdbx.",
        file=sys.stderr,
    )
    sys.exit(2)


def _load_kdbx(input_path: str) -> Tuple[List[SharedFolder], List[Record]]:
    """Parse a Keeper KDBX export into SharedFolders (empty) and Records.

    KDBX does not carry shared folder permission data — that lives only in the
    JSON export. Folder structure is read from KeePass group names and mapped
    to shared_folders / sub_folders on each Record so that --collapse-folders
    works the same way as with JSON input.

    Attachments are loaded into memory for every entry that has them.
    KeePass caps individual attachments at 1MB; oversized blobs are warned
    about but still included (pykeepass reads whatever is stored).
    """
    try:
        from pykeepass import PyKeePass
        from pykeepass.exceptions import CredentialsError
    except ImportError:
        print(
            "ERROR: pykeepass is required for KDBX input.\n"
            "Install it with: pip install pykeepass",
            file=sys.stderr,
        )
        sys.exit(2)

    # Prompt securely — never echo the password
    password = getpass.getpass(f"Enter KeePass password for {os.path.basename(input_path)}: ")

    try:
        kp = PyKeePass(input_path, password=password)
    except CredentialsError:
        print("ERROR: Incorrect KeePass password.", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR opening KDBX file: {e}", file=sys.stderr)
        sys.exit(2)

    records: List[Record] = []

    for entry in kp.entries:
        title = entry.title or "Untitled"
        login = entry.username or None
        password_val = entry.password or None
        login_url = entry.url or None
        notes = entry.notes or None
        # Keeper secure notes may store content in custom string fields
        # (pykeepass: entry.custom_properties is a dict of extra fields).
        if not notes:
            for k, v in (entry.custom_properties or {}).items():
                if isinstance(v, str) and v.strip():
                    notes = v
                    break

        # TOTP: pykeepass exposes otp attribute on entries that have it
        otpauth = None
        try:
            otp = getattr(entry, "otp", None)
            if otp and str(otp).startswith("otpauth://"):
                otpauth = str(otp)
        except Exception:
            pass

        # Build folder path from KeePass group hierarchy.
        # KeePass root group is typically named after the vault — skip it.
        # Groups below root map to: shared_folder = parent, sub_folder = child.
        shared_folders: List[str] = []
        sub_folders: List[str] = []
        folders: List[str] = []

        group = entry.group
        path_parts: List[str] = []
        while group is not None and group.name and group != kp.root_group:
            path_parts.insert(0, group.name)
            group = group.parentgroup

        if len(path_parts) == 0:
            pass  # no folder → goes to employee/fallback vault
        elif len(path_parts) == 1:
            shared_folders.append(path_parts[0])
        else:
            # Use first segment as shared folder, second as sub-folder
            shared_folders.append(path_parts[0])
            sub_folders.append(path_parts[1])

        # Attachments — load into memory, warn if over KeePass 1MB cap
        attachments: List[InMemoryAttachment] = []
        for att in entry.attachments or []:
            size = len(att.data) if att.data else 0
            if size > 1_048_576:
                print(
                    f"WARN: attachment '{att.filename}' on '{title}' is "
                    f"{size // 1024}KB — KeePass caps attachments at 1MB; "
                    f"data may be truncated.",
                    file=sys.stderr,
                )
            if att.data:
                attachments.append(InMemoryAttachment(name=att.filename, content=att.data))

        category = "Login" if (login and password_val) else "Secure Note"

        records.append(
            Record(
                title=title,
                login=login,
                password=password_val,
                login_url=login_url,
                notes=notes,
                otpauth=otpauth,
                shared_folders=shared_folders,
                folders=folders,
                sub_folders=sub_folders,
                category=category,
                attachments=attachments,
            )
        )

    # KDBX carries no shared folder permission data
    return [], records


def read_export_json(
    input_path: str, ctx: InputContext
) -> Tuple[List[SharedFolder], List[Record]]:
    """Parse Keeper data and, for ZIPs, load attachments into memory."""
    if ctx.is_kdbx:
        return _load_kdbx(input_path)

    if ctx.is_zip:
        assert ctx.zf is not None
        raw = json.loads(ctx.zf.read("export.json"))
    else:
        with open(input_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

    shared, records = load_keeper_json(raw)

    # Load attachments into memory from ZIP (never written to disk)
    if ctx.is_zip:
        assert ctx.zf is not None
        namelist = set(ctx.zf.namelist())
        raw_records = raw.get("records", [])
        for rec, raw_rec in zip(records, raw_records):
            for att in raw_rec.get("attachments") or []:
                uid = att.get("file_uid", "")
                if not uid:
                    continue
                blob_path = f"files/{uid}"
                if blob_path not in namelist:
                    print(
                        f"WARN: attachment blob missing in ZIP: {blob_path}",
                        file=sys.stderr,
                    )
                    continue
                display_name = att.get("name") or uid
                # Fall back to mime-based extension if display name has none
                if not os.path.splitext(display_name)[1]:
                    ext = _ext_from_mime(att.get("mime"))
                    if ext:
                        display_name += ext
                content = ctx.zf.read(blob_path)
                rec.attachments.append(
                    InMemoryAttachment(name=display_name, content=content)
                )

    return shared, records


# --------------------------- Build ItemCreateParams (for bulk) ---------------------------


BULK_CREATE_MAX = 100
"""Maximum items per client.items.create_all() call."""


def _chunked(items: List, size: int) -> List[List]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _make_file_params(
    attachments: List[InMemoryAttachment],
    sections: List[ItemSection],
) -> List[FileCreateParams]:
    """Build FileCreateParams from in-memory attachments, adding a section if needed."""
    if not attachments:
        return []
    sections.append(ItemSection(id="files", title="Files"))
    return [
        FileCreateParams(
            name=att.name,
            content=att.content,
            sectionId="files",
            fieldId="file",
        )
        for att in attachments
    ]


def _build_login_params(
    vault_id: str,
    rec: Record,
    attachments: List[InMemoryAttachment],
    tags: Optional[List[str]],
) -> ItemCreateParams:
    fields: List[ItemField] = []
    if rec.login is not None:
        fields.append(
            ItemField(
                id="username",
                value=rec.login,
                title="Username",
                fieldType=ItemFieldType.TEXT,
            )
        )
    if rec.password is not None:
        fields.append(
            ItemField(
                id="password",
                value=rec.password,
                title="Password",
                fieldType=ItemFieldType.CONCEALED,
            )
        )

    sections: List[ItemSection] = []
    if rec.otpauth:
        sections.append(ItemSection(id="sec-otp", title="Two-Factor"))
        fields.append(
            ItemField(
                id="otp",
                title="OTP",
                fieldType=ItemFieldType.TOTP,
                value=rec.otpauth,
                section_id="sec-otp",
            )
        )

    files = _make_file_params(attachments, sections)

    websites: List[Website] = []
    if rec.login_url:
        websites.append(
            Website(
                url=rec.login_url,
                label="site",
                autofill_behavior=AutofillBehavior.ANYWHEREONWEBSITE,
            )
        )

    return ItemCreateParams(
        title=rec.title,
        category=ItemCategory.LOGIN,
        vault_id=vault_id,
        fields=fields or None,
        sections=sections or None,
        notes=rec.notes or None,
        websites=websites or None,
        files=files or None,
        tags=tags or None,
    )


def _build_secure_note_params(
    vault_id: str,
    rec: Record,
    attachments: List[InMemoryAttachment],
    tags: Optional[List[str]],
) -> ItemCreateParams:
    """Build a Secure Note, preserving any login/password/url/otp as fields."""
    fields: List[ItemField] = []
    sections: List[ItemSection] = []

    if rec.login or rec.password or rec.login_url:
        sections.append(ItemSection(id="details", title="Details"))
    if rec.login:
        fields.append(
            ItemField(
                id="username",
                value=rec.login,
                title="Username",
                fieldType=ItemFieldType.TEXT,
                section_id="details",
            )
        )
    if rec.password:
        fields.append(
            ItemField(
                id="password",
                value=rec.password,
                title="Password",
                fieldType=ItemFieldType.CONCEALED,
                section_id="details",
            )
        )
    if rec.login_url:
        fields.append(
            ItemField(
                id="url",
                value=rec.login_url,
                title="URL",
                fieldType=ItemFieldType.TEXT,
                section_id="details",
            )
        )
    if rec.otpauth:
        sections.append(ItemSection(id="sec-otp", title="Two-Factor"))
        fields.append(
            ItemField(
                id="otp",
                title="OTP",
                fieldType=ItemFieldType.TOTP,
                value=rec.otpauth,
                section_id="sec-otp",
            )
        )

    files = _make_file_params(attachments, sections)

    return ItemCreateParams(
        title=rec.title,
        category=ItemCategory.SECURENOTE,
        vault_id=vault_id,
        fields=fields or None,
        notes=rec.notes or None,
        sections=sections or None,
        files=files or None,
        tags=tags or None,
    )


# --------------------------- Planner + bulk create ---------------------------


@dataclass
class _PendingItem:
    """An item queued for creation, with its fingerprint for state tracking."""
    params: ItemCreateParams
    fingerprint: str
    rec: Record


async def plan_and_apply(
    shared_folders: List[SharedFolder],
    records: List[Record],
    *,
    input_path: str,
    employee_vault: str,
    private_prefix: str,
    collapse_folders: bool,
    dry: bool,
    silent: bool,
    user_for_private: Optional[str],
) -> None:
    client = await _get_client()

    # Load resume state (if any)
    completed = load_state(input_path, silent=silent) if not dry else set()

    # Compute shared and private vault names
    def _vault_and_tags(path: str, *, prefix: str = "") -> Tuple[str, List[str]]:
        if collapse_folders:
            parent, child = _split_folder_path(path)
            vault_name = f"{prefix}{parent}"
            # Parent items get the parent tag; child items get parent\child tag only.
            tags = [f"{parent}\\{child}"] if child is not None else [parent]
            return vault_name, tags
        return f"{prefix}{normalize_path_to_name(path)}", []

    # ---------------------------------------------------------------------------
    # Build shared folder vault names + tags from the shared_folders manifest.
    #
    # FIX: shared_tag_map values always default to [sf.path] (the folder name)
    # rather than [] when _vault_and_tags returns no tags (non-collapse mode).
    # This ensures every item in a shared folder gets at least the folder name
    # as a tag, regardless of whether the folder had sub-folders or not.
    # ---------------------------------------------------------------------------
    shared_vault_map: Dict[str, str] = {}
    shared_tag_map: Dict[str, List[str]] = {}
    for sf in shared_folders:
        vault_name, tags = _vault_and_tags(sf.path)
        shared_vault_map[sf.path] = vault_name
        # Always tag with at least the folder name — tags may be [] in
        # non-collapse mode for top-level paths, so fall back to [sf.path].
        shared_tag_map[sf.path] = tags if tags else [sf.path]

    private_vault_map: Dict[str, str] = {}
    private_tag_map: Dict[str, List[str]] = {}
    non_shared_folders: Set[str] = set()
    for r in records:
        for f in r.folders:
            non_shared_folders.add(f)
    for folder in sorted(non_shared_folders):
        vault_name, tags = _vault_and_tags(folder, prefix=private_prefix)
        private_vault_map[folder] = vault_name
        # Always tag with at least the folder name.
        private_tag_map[folder] = tags if tags else [folder]

    # All vault names we'll use, accounting for sub-folder routing.
    # FIX: when a record references a shared folder not in the manifest,
    # ensure shared_tag_map is populated with at least the folder name.
    vault_names_used: Set[str] = {employee_vault}
    for rec in records:
        for i, sf in enumerate(rec.shared_folders):
            has_sub = i < len(rec.sub_folders)
            sub = rec.sub_folders[i] if has_sub else None
            if has_sub and not collapse_folders:
                # Without --collapse-folders: child gets its own vault named
                # after the child folder only (no parent prefix).
                if sub not in shared_vault_map:
                    shared_vault_map[sub] = sub
                    shared_tag_map[sub] = [f"{sf}\\{sub}"]
                vault_names_used.add(sub)
            else:
                if sf not in shared_vault_map:
                    vault_name, _ = _vault_and_tags(sf)
                    shared_vault_map[sf] = vault_name
                    # FIX: always fall back to [sf] so the tag is never empty.
                    shared_tag_map[sf] = [sf]
                vault_names_used.add(shared_vault_map[sf])
        for f in rec.folders:
            if f not in private_vault_map:
                vault_name, tags = _vault_and_tags(f, prefix=private_prefix)
                private_vault_map[f] = vault_name
                # FIX: always fall back to [f] so the tag is never empty.
                private_tag_map[f] = tags if tags else [f]
            vault_names_used.add(private_vault_map[f])

    if not silent:
        print(
            f"Using {len(vault_names_used)} vault(s) for import: {', '.join(sorted(vault_names_used))}"
        )

    # Ensure every vault exists (create via SDK if missing)
    name_to_id, vault_titles = await _vault_name_to_id_map(client)
    need_create = [
        v for v in vault_names_used
        if v not in name_to_id and _normalize_vault_name(v) not in name_to_id
    ]
    if need_create and not silent:
        print(f"Vault(s) to create: {', '.join(sorted(need_create))}")
    for v in sorted(need_create):
        await _ensure_vault(client, v, name_to_id, dry=dry, silent=silent)
    if not dry and need_create:
        name_to_id, vault_titles = await _vault_name_to_id_map(client)
        if not silent:
            print(f"Vaults after create ({len(vault_titles)}): {', '.join(vault_titles)}")

    # Resolve vault names to IDs (for SDK group grants and item creation)
    resolved: Dict[str, str] = {}
    for v in vault_names_used:
        if dry and v in need_create:
            resolved[v] = ""
        else:
            resolved[v] = _resolve_vault_id(name_to_id, v)

    # Apply permission mapping: groups via SDK, users via op CLI
    for sf in shared_folders:
        vault_name = shared_vault_map[sf.path]
        vault_id = resolved[vault_name]
        for perm in sf.permissions:
            if perm.is_group:
                await _grant_group_permissions_sdk(
                    client,
                    vault_id,
                    perm.name,
                    manage_users=perm.manage_users,
                    manage_records=perm.manage_records,
                    dry=dry,
                    silent=silent,
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

    if user_for_private:
        _grant_user_permissions(
            employee_vault,
            user_for_private,
            manage_users=True,
            manage_records=True,
            dry=dry,
            silent=silent,
        )

    # ---------------------------------------------------------------------------
    # _destinations: resolve a record's (vault_name, tags) destinations.
    #
    # FIX: fall back to [sf] as tag when shared_tag_map has no entry for a
    # folder key — guards against any remaining key-mismatch edge cases (e.g.
    # whitespace differences between manifest path and record folder string).
    # ---------------------------------------------------------------------------
    def _destinations(rec: Record) -> List[Tuple[str, List[str]]]:
        dests: List[Tuple[str, List[str]]] = []
        for i, sf in enumerate(rec.shared_folders):
            has_sub = i < len(rec.sub_folders)
            sub = rec.sub_folders[i] if has_sub else None

            if has_sub and not collapse_folders:
                # Without --collapse-folders: child gets its own vault,
                # tagged with Parent\Child only.
                dests.append((sub, [f"{sf}\\{sub}"]))
            else:
                # FIX: fall back to [sf] if the key is absent or maps to [].
                base_tags = shared_tag_map.get(sf) or [sf]
                # With --collapse-folders: child gets Parent\Child tag
                if has_sub:
                    base_tags = [f"{sf}\\{sub}"]
                dests.append((shared_vault_map[sf], base_tags))
        for f in rec.folders:
            if f not in private_vault_map:
                vn, tg = _vault_and_tags(f, prefix=private_prefix)
                private_vault_map[f] = vn
                # FIX: always fall back to [f] so the tag is never empty.
                private_tag_map[f] = tg if tg else [f]
            dests.append((private_vault_map[f], private_tag_map.get(f) or [f]))
        return dests or [(employee_vault, [])]

    if dry:
        for rec in records:
            for vault_name, tags in _destinations(rec):
                kind = "LOGIN" if rec.category == "Login" else "NOTE"
                names = [a.name for a in rec.attachments]
                msg = f"DRY-RUN: {kind} '{rec.title}' → vault '{vault_name}'"
                if tags:
                    msg += f" tags={tags}"
                if rec.category == "Login" and rec.otpauth:
                    msg += " with TOTP"
                if names:
                    msg += f" with files {names}"
                if rec.notes:
                    msg += f" notes='{rec.notes[:40]}{'...' if len(rec.notes) > 40 else ''}'"
                print(msg)
        return

    # Build (vault_id -> list of _PendingItem) for bulk create, skipping completed items
    batches: Dict[str, List[_PendingItem]] = defaultdict(list)
    skipped = 0

    for rec in records:
        for vault_name, tags in _destinations(rec):
            vault_id = resolved[vault_name]
            fp = _item_fingerprint(vault_id, rec)

            if fp in completed:
                skipped += 1
                continue

            if rec.category == "Login":
                params = _build_login_params(vault_id, rec, rec.attachments, tags or None)
            else:
                params = _build_secure_note_params(vault_id, rec, rec.attachments, tags or None)
            batches[vault_id].append(_PendingItem(params=params, fingerprint=fp, rec=rec))

    if skipped and not silent:
        print(f"⏭  Skipping {skipped} already-completed items")

    total_remaining = sum(len(v) for v in batches.values())
    if total_remaining == 0:
        if not silent:
            print("✔ All items already imported — nothing to do")
        delete_state(input_path, silent=silent)
        return

    if not silent:
        print(f"📦 {total_remaining} items to create")

    # Bulk create per vault, in chunks of BULK_CREATE_MAX
    rate_limited = False
    id_to_name = {vid: name for name, vid in resolved.items()}

    for vault_id, pending_list in batches.items():
        if not pending_list or rate_limited:
            continue
        vault_title = id_to_name.get(vault_id, vault_id)
        if not silent:
            print(f"Creating {len(pending_list)} item(s) in vault '{vault_title}'...")
        total_ok = 0

        for chunk in _chunked(pending_list, BULK_CREATE_MAX):
            try:
                resp: ItemsUpdateAllResponse = await client.items.create_all(
                    vault_id, [item.params for item in chunk]
                )
            except Exception as e:
                if _is_rate_limit_error(e):
                    print(
                        f"\n⚠  Rate limited during bulk create in vault "
                        f"'{vault_title}'. Saving progress...",
                        file=sys.stderr,
                    )
                    rate_limited = True
                    break
                print(f"ERROR bulk create in vault {vault_title}: {e}", file=sys.stderr)
                continue

            for i, ir in enumerate(resp.individual_responses):
                if ir.error is not None:
                    err_str = str(ir.error).lower()
                    if "429" in err_str or "rate limit" in err_str:
                        print(
                            f"\n⚠  Rate limited on item '{chunk[i].rec.title}'. "
                            f"Saving progress...",
                            file=sys.stderr,
                        )
                        rate_limited = True
                        break
                    title = chunk[i].params.title if i < len(chunk) else "?"
                    print(
                        f"ERROR creating item '{title}' in vault: {ir.error}",
                        file=sys.stderr,
                    )
                else:
                    completed.add(chunk[i].fingerprint)
                    total_ok += 1

            if rate_limited:
                break

        if not silent:
            print(
                f"✔ Bulk created {total_ok}/{len(pending_list)} items in vault '{vault_title}'"
            )

    if rate_limited:
        save_state(input_path, completed, silent=silent)
        print(
            f"\n🔄 Import paused due to rate limiting. "
            f"Re-run the same command to resume.",
            file=sys.stderr,
        )
        sys.exit(3)
    else:
        delete_state(input_path, silent=silent)
        if not silent:
            print(f"\n✅ Import complete — {len(completed)} items created")


# --------------------------- Entrypoint ---------------------------


async def main() -> None:
    ap = argparse.ArgumentParser(
        description="Keeper → 1Password migration with attachments (SDK-only bulk create)"
    )
    ap.add_argument(
        "--input",
        required=True,
        help="Path to .zip (export with files), .json (data only, no attachments), or .kdbx",
    )
    ap.add_argument(
        "--employee-vault",
        required=True,
        help="Name of the fallback vault for items without folders",
    )
    ap.add_argument(
        "--private-prefix",
        default="Private - ",
        help="Prefix for private vault names (default: 'Private - ')",
    )
    ap.add_argument(
        "--collapse-folders",
        action="store_true",
        help=(
            "Collapse sub-folders into parent vault. "
            "Without this flag, sub-folders become their own vault."
        ),
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

    ctx = open_input_container(args.input)
    if not args.silent:
        if ctx.is_kdbx:
            print("Input is KDBX; importing credentials + attachments (≤1MB each). Note: no shared folder permissions in KDBX.")
        elif ctx.is_zip:
            print("Input is ZIP; importing credentials, folder structure, and attachments.")
        else:
            print("Input is JSON; importing without attachments.")
    try:
        shared, records = read_export_json(args.input, ctx)
    except Exception as e:
        print(f"Failed to parse input: {e}", file=sys.stderr)
        sys.exit(2)

    if not args.silent:
        att_count = sum(len(r.attachments) for r in records)
        msg = f"Loaded {len(shared)} shared folders and {len(records)} records from {os.path.basename(args.input)}"
        if att_count:
            msg += f" ({att_count} attachments in memory)"
        print(msg)

    await plan_and_apply(
        shared,
        records,
        input_path=os.path.abspath(args.input),
        employee_vault=args.employee_vault,
        private_prefix=args.private_prefix,
        collapse_folders=args.collapse_folders,
        dry=args.dry_run,
        silent=args.silent,
        user_for_private=args.user_for_private,
    )


if __name__ == "__main__":
    asyncio.run(main())