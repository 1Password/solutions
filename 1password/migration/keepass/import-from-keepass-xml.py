#!/usr/bin/env python3
"""
KeePass XML → 1Password migration helper — SDK bulk create

Reads a KeePass XML export (.xml, produced via File → Export → KeePass XML 2.x
in KeePass or compatible apps) and imports every entry into 1Password using the
onepassword-sdk bulk-create API.

PASSWORD HISTORY
  Each entry's <History> child entries are collected, deduplicated, and appended
  to the item's Notes field as a human-readable block:

      --- Password History ---
      2024-01-15T09:23:00Z  hunter2
      2023-06-01T14:00:00Z  correct-horse

  The most-recent value in <History> that differs from the current password is
  listed first (newest → oldest). Duplicate passwords are suppressed.

FOLDER → VAULT MAPPING
  Without --collapse-folders:
    Each KeePass group path (e.g. "Email/Work") becomes its own vault.
  With --collapse-folders:
    All items land in the top-level group vault; sub-group names become tags.

ATTACHMENTS
  Binary attachments stored in <Binary> elements are imported as 1Password
  file attachments. KeePass stores them base64-encoded inside the XML.

RESUMABILITY
  On interruption (e.g. rate-limit / 429) a state file is written next to the
  input file. Re-running the same command resumes automatically.

REQUIREMENTS
  - OP_SERVICE_ACCOUNT_TOKEN env var
  - onepassword-sdk  (auto-installed into .venv-1pw if missing)
  - `op` CLI in PATH  (only needed for user vault permission grants)

USAGE
  python import-from-keepass-xml.py \\
    --input keepass-export.xml \\
    --employee-vault "KeePass Import" \\
    [--private-prefix "Private - "] \\
    [--collapse-folders] \\
    [--dry-run] \\
    [--silent] \\
    [--user-for-private user@example.com]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Auto-install: create a venv next to this script if the SDK is missing.
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

    if sys.executable == _venv_python:
        print("ERROR: onepassword-sdk failed to import even inside the venv.", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(_venv_python):
        print(f"Creating virtual environment at {_venv_dir}...")
        _venv.create(_venv_dir, with_pip=True)

    _req_file = os.path.join(_script_dir, "requirements.txt")
    if os.path.isfile(_req_file):
        print(f"Installing packages from {_req_file}...")
        _sp.check_call([_venv_python, "-m", "pip", "install", "--quiet", "-r", _req_file])
    else:
        print("Installing onepassword-sdk...")
        _sp.check_call([_venv_python, "-m", "pip", "install", "--quiet", "onepassword-sdk"])

    print("Restarting inside virtual environment...\n")
    os.execv(_venv_python, [_venv_python] + sys.argv)


# ---------------------------------------------------------------------------
# 1Password client helpers  (identical pattern to the Keeper migration script)
# ---------------------------------------------------------------------------

async def _get_client() -> Client:
    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
    if not token:
        raise RuntimeError("OP_SERVICE_ACCOUNT_TOKEN is not set")
    return await Client.authenticate(
        auth=token,
        integration_name="KeePassXMLImporter",
        integration_version="v1",
    )


def _normalize_vault_name(name: str) -> str:
    s = " ".join(name.split())
    return s.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")


async def _vault_name_to_id_map(client: Client) -> Tuple[Dict[str, str], List[str]]:
    vaults = await client.vaults.list(VaultListParams(decrypt_details=True))
    name_to_id: Dict[str, str] = {}
    seen: Set[str] = set()
    for v in vaults:
        name_to_id[v.title] = v.id
        seen.add(v.title)
        n = _normalize_vault_name(v.title)
        if n != v.title:
            name_to_id[n] = v.id
    return name_to_id, sorted(seen)


def _resolve_vault_id(name_to_id: Dict[str, str], vault_name: str) -> str:
    if vault_name in name_to_id:
        return name_to_id[vault_name]
    n = _normalize_vault_name(vault_name)
    if n in name_to_id:
        return name_to_id[n]
    candidates = [k for k in name_to_id if k != "[Encrypted]"]
    suggestions = difflib.get_close_matches(vault_name, candidates, n=1, cutoff=0.6)
    msg = f"Vault not found: {vault_name!r}."
    if suggestions:
        msg += f" Did you mean {suggestions[0]!r}?"
    msg += f" Available: {', '.join(sorted(candidates)[:15])}"
    raise ValueError(msg)


async def _ensure_vault(
    client: Client,
    vault_name: str,
    name_to_id: Dict[str, str],
    *,
    dry: bool,
    silent: bool,
) -> Optional[str]:
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
    name_to_id[vault_name] = created.id
    n = _normalize_vault_name(vault_name)
    if n != vault_name:
        name_to_id[n] = created.id
    return created.id


# Permission bitmasks
_PERM_VIEWING  = READ_ITEMS | REVEAL_ITEM_PASSWORD | UPDATE_ITEM_HISTORY
_PERM_EDITING  = _PERM_VIEWING | CREATE_ITEMS | UPDATE_ITEMS | ARCHIVE_ITEMS | DELETE_ITEMS | IMPORT_ITEMS | EXPORT_ITEMS | SEND_ITEMS | PRINT_ITEMS
_PERM_MANAGING = _PERM_EDITING | MANAGE_VAULT


def _perms_list(manage_users: bool, manage_records: bool) -> List[str]:
    perms = ["allow_viewing"]
    if manage_records:
        perms.append("allow_editing")
    if manage_users:
        perms.append("allow_managing")
    return perms


def _run_op(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


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
    cmd = ["op", "vault", "user", "grant", "--no-input",
           "--vault", vault_name, "--user", user_name,
           "--permissions", ",".join(perms)]
    proc = _run_op(cmd)
    if proc.returncode != 0:
        print(f"WARN granting user {user_name!r} on {vault_name!r}: {proc.stderr.strip()}", file=sys.stderr)
    elif not silent:
        print(f"✔ Granted user {user_name!r} on vault {vault_name!r}: {perms}")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PasswordHistoryEntry:
    """A single historical password with its last-modification timestamp."""
    timestamp: str   # ISO-8601 string from KeePass <LastModificationTime>
    password: str


@dataclass
class InMemoryAttachment:
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
    group_path: List[str]          # e.g. ["Email", "Work"]
    attachments: List[InMemoryAttachment] = field(default_factory=list)
    password_history: List[PasswordHistoryEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Resumable state file
# ---------------------------------------------------------------------------

def _item_fingerprint(vault_id: str, rec: Record) -> str:
    parts = [
        vault_id,
        rec.title,
        rec.login or "",
        rec.password or "",
        rec.login_url or "",
        rec.otpauth or "",
        ",".join(sorted(a.name for a in rec.attachments)),
    ]
    raw = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _state_file_path(input_path: str) -> str:
    base = os.path.splitext(input_path)[0]
    return f"{base}.import-state.json"


def _compute_checksum(fingerprints: List[str]) -> str:
    payload = "\n".join(sorted(fingerprints)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_state(input_path: str, *, silent: bool) -> Set[str]:
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
    path = _state_file_path(input_path)
    fingerprints = sorted(completed)
    data = {"checksum": _compute_checksum(fingerprints), "completed": fingerprints, "count": len(fingerprints)}
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)
    if not silent:
        print(f"💾 State saved: {len(fingerprints)} items completed → {path}")


def delete_state(input_path: str, *, silent: bool) -> None:
    path = _state_file_path(input_path)
    if os.path.isfile(path):
        os.remove(path)
        if not silent:
            print("🗑  Removed state file (import complete)")


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


# ---------------------------------------------------------------------------
# KeePass XML parser
# ---------------------------------------------------------------------------

def _text(el: Optional[ET.Element], tag: str, default: str = "") -> str:
    """Return stripped text of a direct child element, or default."""
    if el is None:
        return default
    child = el.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _find_string_value(entry_el: ET.Element, key: str) -> Optional[str]:
    """Return the Value text for the first <String><Key>key</Key>...</String> block."""
    for s in entry_el.findall("String"):
        k = _text(s, "Key")
        if k == key:
            v = s.find("Value")
            if v is not None and v.text:
                return v.text.strip()
            return None
    return None


_OTPAUTH_RE = re.compile(r"otpauth://[^\s]+")

def _extract_otpauth(entry_el: ET.Element) -> Optional[str]:
    """Look for an otpauth:// URI in any String value or the Notes field."""
    for s in entry_el.findall("String"):
        v = s.find("Value")
        if v is not None and v.text:
            m = _OTPAUTH_RE.search(v.text)
            if m:
                return m.group(0)
    return None


def _parse_history(entry_el: ET.Element, current_password: Optional[str]) -> List[PasswordHistoryEntry]:
    """
    Extract <History><Entry>…</Entry></History> blocks.

    Each historical entry has its own <String> blocks with Password and a
    <Times><LastModificationTime> timestamp. We collect all distinct passwords
    (newest first) that differ from the current password, deduplicating exact
    repeats.
    """
    history_el = entry_el.find("History")
    if history_el is None:
        return []

    entries: List[Tuple[str, str]] = []  # (timestamp, password)
    for h_entry in history_el.findall("Entry"):
        pwd = _find_string_value(h_entry, "Password")
        if not pwd:
            continue
        times = h_entry.find("Times")
        ts = _text(times, "LastModificationTime") if times is not None else ""
        entries.append((ts, pwd))

    # Reverse so newest is first (KeePass stores oldest→newest)
    entries.reverse()

    seen: Set[str] = {current_password or ""}
    result: List[PasswordHistoryEntry] = []
    for ts, pwd in entries:
        if pwd in seen:
            continue
        seen.add(pwd)
        result.append(PasswordHistoryEntry(timestamp=ts, password=pwd))

    return result


def _format_history_block(history: List[PasswordHistoryEntry]) -> str:
    """Render password history as a plain-text block for the Notes field."""
    if not history:
        return ""
    lines = ["--- Password History ---"]
    for h in history:
        ts = h.timestamp or "unknown time"
        lines.append(f"{ts}  {h.password}")
    return "\n".join(lines)


def _parse_attachments(entry_el: ET.Element, binary_pool: Dict[str, bytes]) -> List[InMemoryAttachment]:
    """
    KeePass XML stores attachment content in a global <Meta><Binaries> pool,
    referenced by Ref id from <Entry><Binary><Value Ref="N"/></Binary>.
    Falls back to inline base64 content if Ref is absent.
    """
    attachments: List[InMemoryAttachment] = []
    for bin_el in entry_el.findall("Binary"):
        name = _text(bin_el, "Key")
        if not name:
            continue
        val_el = bin_el.find("Value")
        if val_el is None:
            continue
        ref = val_el.get("Ref")
        if ref is not None:
            content = binary_pool.get(ref)
            if content is None:
                print(f"WARN: attachment ref {ref!r} ('{name}') not found in binary pool", file=sys.stderr)
                continue
        else:
            # Inline base64
            raw = (val_el.text or "").strip()
            if not raw:
                continue
            try:
                content = base64.b64decode(raw)
            except Exception as e:
                print(f"WARN: could not decode attachment '{name}': {e}", file=sys.stderr)
                continue
        attachments.append(InMemoryAttachment(name=name, content=content))
    return attachments


def _build_binary_pool(root: ET.Element) -> Dict[str, bytes]:
    """
    Build a {ref_id: bytes} map from <Meta><Binaries><Binary id="N">…</Binary></Binaries></Meta>.
    Content is base64-encoded in the XML.
    """
    pool: Dict[str, bytes] = {}
    meta = root.find("Meta")
    if meta is None:
        return pool
    binaries = meta.find("Binaries")
    if binaries is None:
        return pool
    for b in binaries.findall("Binary"):
        ref_id = b.get("ID") or b.get("id")
        if ref_id is None:
            continue
        raw = (b.text or "").strip()
        if not raw:
            pool[ref_id] = b""
            continue
        try:
            compressed = b.get("Compressed", "False").lower() == "true"
            data = base64.b64decode(raw)
            if compressed:
                import zlib
                data = zlib.decompress(data, wbits=-15)  # raw deflate
            pool[ref_id] = data
        except Exception as e:
            print(f"WARN: could not decode binary pool entry id={ref_id}: {e}", file=sys.stderr)
    return pool


def _walk_group(
    group_el: ET.Element,
    path: List[str],
    binary_pool: Dict[str, bytes],
    records: List[Record],
    *,
    skip_recycle_bin: bool = True,
) -> None:
    """Recursively walk a <Group> element, collecting entries into `records`."""
    group_name = _text(group_el, "Name")

    # Skip the KeePass Recycle Bin group
    is_recycler = group_el.find("IsAutoType")  # not reliable; use name heuristic
    if skip_recycle_bin and group_name in ("Recycle Bin", "$RecycleBin"):
        return

    current_path = path + [group_name] if group_name else path

    for entry_el in group_el.findall("Entry"):
        # Skip entries that are themselves History entries (they're nested under
        # <History> inside their parent entry, not direct children of the group —
        # but defensive check doesn't hurt)
        if entry_el.find("History") is None and entry_el.getparent() is not None:
            pass  # ElementTree doesn't expose getparent; this is always fine

        title    = _find_string_value(entry_el, "Title") or "Untitled"
        login    = _find_string_value(entry_el, "UserName") or None
        password = _find_string_value(entry_el, "Password") or None
        url      = _find_string_value(entry_el, "URL") or None
        notes    = _find_string_value(entry_el, "Notes") or None
        otpauth  = _extract_otpauth(entry_el)

        # Suppress the otpauth string from appearing raw in notes
        if notes and otpauth and otpauth in notes:
            notes = notes.replace(otpauth, "").strip() or None

        history = _parse_history(entry_el, password)
        attachments = _parse_attachments(entry_el, binary_pool)

        records.append(Record(
            title=title,
            login=login,
            password=password,
            login_url=url,
            notes=notes,
            otpauth=otpauth,
            group_path=current_path,
            attachments=attachments,
            password_history=history,
        ))

    # Recurse into sub-groups
    for sub_group in group_el.findall("Group"):
        _walk_group(sub_group, current_path, binary_pool, records, skip_recycle_bin=skip_recycle_bin)


def load_keepass_xml(input_path: str) -> List[Record]:
    """Parse a KeePass XML 2.x export file and return a flat list of Records."""
    try:
        tree = ET.parse(input_path)
    except ET.ParseError as e:
        print(f"ERROR: Failed to parse XML: {e}", file=sys.stderr)
        sys.exit(2)

    root = tree.getroot()
    if root.tag != "KeePassFile":
        print(f"ERROR: Expected root tag <KeePassFile>, got <{root.tag}>. "
              "Is this a KeePass XML 2.x export?", file=sys.stderr)
        sys.exit(2)

    binary_pool = _build_binary_pool(root)

    records: List[Record] = []
    db_root = root.find("Root")
    if db_root is None:
        print("ERROR: <Root> element not found in KeePass XML.", file=sys.stderr)
        sys.exit(2)

    root_group = db_root.find("Group")
    if root_group is None:
        print("ERROR: No root <Group> found.", file=sys.stderr)
        sys.exit(2)

    # The outermost group is the database name — skip it from path labelling.
    for entry_el in root_group.findall("Entry"):
        title    = _find_string_value(entry_el, "Title") or "Untitled"
        login    = _find_string_value(entry_el, "UserName") or None
        password = _find_string_value(entry_el, "Password") or None
        url      = _find_string_value(entry_el, "URL") or None
        notes    = _find_string_value(entry_el, "Notes") or None
        otpauth  = _extract_otpauth(entry_el)
        if notes and otpauth and otpauth in notes:
            notes = notes.replace(otpauth, "").strip() or None
        history = _parse_history(entry_el, password)
        attachments = _parse_attachments(entry_el, binary_pool)
        records.append(Record(
            title=title, login=login, password=password,
            login_url=url, notes=notes, otpauth=otpauth,
            group_path=[],   # top-level items have no group path
            attachments=attachments, password_history=history,
        ))

    for sub_group in root_group.findall("Group"):
        _walk_group(sub_group, [], binary_pool, records)

    return records


# ---------------------------------------------------------------------------
# Notes field builder — merges original notes + history block
# ---------------------------------------------------------------------------

def _build_notes(rec: Record) -> Optional[str]:
    parts: List[str] = []
    if rec.notes:
        parts.append(rec.notes)
    if rec.password_history:
        parts.append(_format_history_block(rec.password_history))
    return "\n\n".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Vault name derivation from group path
# ---------------------------------------------------------------------------

def _path_to_vault_and_tags(
    group_path: List[str],
    *,
    prefix: str,
    collapse_folders: bool,
) -> Tuple[str, List[str]]:
    """
    Map a group_path list to (vault_name, tags).

    Without --collapse-folders: vault = prefix + full/path; no tags.
    With --collapse-folders:   vault = prefix + top-level group;
                                tag  = "Parent\\Child\\Deeper" for sub-paths.
    """
    if not group_path:
        return "", []  # caller uses employee_vault as fallback

    if not collapse_folders:
        vault_name = prefix + "/".join(group_path)
        return vault_name, []

    # collapse: parent vault only
    vault_name = prefix + group_path[0]
    if len(group_path) == 1:
        tags = [group_path[0]]
    else:
        tags = ["\\".join(group_path)]
    return vault_name, tags


# ---------------------------------------------------------------------------
# ItemCreateParams builders
# ---------------------------------------------------------------------------

BULK_CREATE_MAX = 100

def _chunked(items: List, size: int) -> List[List]:
    return [items[i: i + size] for i in range(0, len(items), size)]


def _make_file_params(
    attachments: List[InMemoryAttachment],
    sections: List[ItemSection],
) -> List[FileCreateParams]:
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
    notes: Optional[str],
    tags: Optional[List[str]],
) -> ItemCreateParams:
    fields: List[ItemField] = []
    if rec.login is not None:
        fields.append(ItemField(id="username", value=rec.login, title="Username", fieldType=ItemFieldType.TEXT))
    if rec.password is not None:
        fields.append(ItemField(id="password", value=rec.password, title="Password", fieldType=ItemFieldType.CONCEALED))

    sections: List[ItemSection] = []
    if rec.otpauth:
        sections.append(ItemSection(id="sec-otp", title="Two-Factor"))
        fields.append(ItemField(id="otp", title="OTP", fieldType=ItemFieldType.TOTP, value=rec.otpauth, section_id="sec-otp"))

    files = _make_file_params(rec.attachments, sections)

    websites: List[Website] = []
    if rec.login_url:
        websites.append(Website(url=rec.login_url, label="site", autofill_behavior=AutofillBehavior.ANYWHEREONWEBSITE))

    return ItemCreateParams(
        title=rec.title,
        category=ItemCategory.LOGIN,
        vault_id=vault_id,
        fields=fields or None,
        sections=sections or None,
        notes=notes or None,
        websites=websites or None,
        files=files or None,
        tags=tags or None,
    )


def _build_secure_note_params(
    vault_id: str,
    rec: Record,
    notes: Optional[str],
    tags: Optional[List[str]],
) -> ItemCreateParams:
    fields: List[ItemField] = []
    sections: List[ItemSection] = []

    if rec.login or rec.password or rec.login_url:
        sections.append(ItemSection(id="details", title="Details"))
    if rec.login:
        fields.append(ItemField(id="username", value=rec.login, title="Username", fieldType=ItemFieldType.TEXT, section_id="details"))
    if rec.password:
        fields.append(ItemField(id="password", value=rec.password, title="Password", fieldType=ItemFieldType.CONCEALED, section_id="details"))
    if rec.login_url:
        fields.append(ItemField(id="url", value=rec.login_url, title="URL", fieldType=ItemFieldType.TEXT, section_id="details"))
    if rec.otpauth:
        sections.append(ItemSection(id="sec-otp", title="Two-Factor"))
        fields.append(ItemField(id="otp", title="OTP", fieldType=ItemFieldType.TOTP, value=rec.otpauth, section_id="sec-otp"))

    files = _make_file_params(rec.attachments, sections)

    return ItemCreateParams(
        title=rec.title,
        category=ItemCategory.SECURENOTE,
        vault_id=vault_id,
        fields=fields or None,
        notes=notes or None,
        sections=sections or None,
        files=files or None,
        tags=tags or None,
    )


def _categorize(rec: Record) -> str:
    """Determine the 1Password category for a KeePass entry."""
    if rec.login and rec.password:
        return "Login"
    if rec.password:
        return "Login"
    return "Secure Note"


# ---------------------------------------------------------------------------
# Planner + bulk create
# ---------------------------------------------------------------------------

@dataclass
class _PendingItem:
    params: ItemCreateParams
    fingerprint: str
    rec: Record


async def plan_and_apply(
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
    completed = load_state(input_path, silent=silent) if not dry else set()

    # Collect all vault names we'll need
    vault_set: Set[str] = {employee_vault}
    for rec in records:
        vn, _ = _path_to_vault_and_tags(rec.group_path, prefix=private_prefix, collapse_folders=collapse_folders)
        if vn:
            vault_set.add(vn)

    if not silent:
        print(f"Using {len(vault_set)} vault(s): {', '.join(sorted(vault_set))}")

    # Ensure all vaults exist
    name_to_id, vault_titles = await _vault_name_to_id_map(client)
    need_create = [v for v in vault_set if v not in name_to_id and _normalize_vault_name(v) not in name_to_id]
    if need_create and not silent:
        print(f"Vault(s) to create: {', '.join(sorted(need_create))}")
    for v in sorted(need_create):
        await _ensure_vault(client, v, name_to_id, dry=dry, silent=silent)
    if not dry and need_create:
        name_to_id, vault_titles = await _vault_name_to_id_map(client)

    resolved: Dict[str, str] = {}
    for v in vault_set:
        if dry and v in need_create:
            resolved[v] = ""
        else:
            resolved[v] = _resolve_vault_id(name_to_id, v)

    # Optional user grants on private vaults
    if user_for_private:
        for vn in vault_set:
            _grant_user_permissions(
                vn, user_for_private,
                manage_users=(vn == employee_vault),
                manage_records=True,
                dry=dry, silent=silent,
            )

    if dry:
        for rec in records:
            vn, tags = _path_to_vault_and_tags(rec.group_path, prefix=private_prefix, collapse_folders=collapse_folders)
            vault_name = vn or employee_vault
            category = _categorize(rec)
            hist_count = len(rec.password_history)
            att_names = [a.name for a in rec.attachments]
            msg = f"DRY-RUN: {category.upper()} '{rec.title}' → vault '{vault_name}'"
            if tags:
                msg += f" tags={tags}"
            if rec.otpauth:
                msg += " +TOTP"
            if hist_count:
                msg += f" +{hist_count} history entries"
            if att_names:
                msg += f" +files {att_names}"
            print(msg)
        return

    # Build batches per vault_id
    batches: Dict[str, List[_PendingItem]] = defaultdict(list)
    skipped = 0

    for rec in records:
        vn, tags = _path_to_vault_and_tags(rec.group_path, prefix=private_prefix, collapse_folders=collapse_folders)
        vault_name = vn or employee_vault
        vault_id = resolved[vault_name]
        fp = _item_fingerprint(vault_id, rec)

        if fp in completed:
            skipped += 1
            continue

        notes = _build_notes(rec)
        category = _categorize(rec)

        if category == "Login":
            params = _build_login_params(vault_id, rec, notes, tags or None)
        else:
            params = _build_secure_note_params(vault_id, rec, notes, tags or None)

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
                    print(f"\n⚠  Rate limited in vault '{vault_title}'. Saving progress...", file=sys.stderr)
                    rate_limited = True
                    break
                print(f"ERROR bulk create in vault {vault_title}: {e}", file=sys.stderr)
                continue

            for i, ir in enumerate(resp.individual_responses):
                if ir.error is not None:
                    err_str = str(ir.error).lower()
                    if "429" in err_str or "rate limit" in err_str:
                        print(f"\n⚠  Rate limited on item '{chunk[i].rec.title}'. Saving progress...", file=sys.stderr)
                        rate_limited = True
                        break
                    title = chunk[i].params.title if i < len(chunk) else "?"
                    print(f"ERROR creating '{title}': {ir.error}", file=sys.stderr)
                else:
                    completed.add(chunk[i].fingerprint)
                    total_ok += 1

            if rate_limited:
                break

        if not silent:
            print(f"✔ Bulk created {total_ok}/{len(pending_list)} items in vault '{vault_title}'")

    if rate_limited:
        save_state(input_path, completed, silent=silent)
        print("\n🔄 Import paused due to rate limiting. Re-run the same command to resume.", file=sys.stderr)
        sys.exit(3)
    else:
        delete_state(input_path, silent=silent)
        if not silent:
            print(f"\n✅ Import complete — {len(completed)} items created")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main() -> None:
    ap = argparse.ArgumentParser(
        description="KeePass XML → 1Password migration (SDK bulk create, password history in notes)"
    )
    ap.add_argument("--input", required=True, help="Path to KeePass XML 2.x export (.xml)")
    ap.add_argument("--employee-vault", required=True, help="Fallback vault for items without a group")
    ap.add_argument("--private-prefix", default="", help="Prefix for vault names derived from groups (default: none)")
    ap.add_argument("--collapse-folders", action="store_true",
                    help="Collapse sub-groups into the parent vault; sub-groups become tags")
    ap.add_argument("--dry-run", action="store_true", help="Print planned actions without creating anything")
    ap.add_argument("--silent", action="store_true", help="Suppress progress output")
    ap.add_argument("--user-for-private", help="Grant this user (email) edit access to all vaults")

    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: File not found: {args.input}", file=sys.stderr)
        sys.exit(2)

    if not args.silent:
        print(f"Parsing KeePass XML: {args.input}")

    try:
        records = load_keepass_xml(args.input)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Failed to parse KeePass XML: {e}", file=sys.stderr)
        sys.exit(2)

    if not args.silent:
        att_count  = sum(len(r.attachments) for r in records)
        hist_count = sum(len(r.password_history) for r in records)
        print(
            f"Loaded {len(records)} entries"
            + (f" ({att_count} attachments)" if att_count else "")
            + (f" ({hist_count} historical passwords across all entries)" if hist_count else "")
        )

    await plan_and_apply(
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
