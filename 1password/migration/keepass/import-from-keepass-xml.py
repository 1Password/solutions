#!/usr/bin/env python3
"""
KeePass XML → 1Password migration helper — SDK bulk create

Reads a KeePass XML export (.xml, produced via File → Export → KeePass XML 2.x
in KeePass or compatible apps) and imports every entry into a single 1Password
vault using the onepassword-sdk bulk-create API.

The vault is created by the service account if it does not already exist.

FOLDER → TAG MAPPING
  KeePass group paths are converted to tags on each item:
    - Top-level group "Email"         → tag "Email"
    - Nested group "Email/Work"       → tags "Email" and "Email/Work"
  Items at the database root (no group) receive no tags.

PASSWORD HISTORY
  KeePass password history is replayed as real 1Password item history:
    1. The item is created with the oldest historical password.
    2. The item is updated (put) once per subsequent historical password,
       oldest → newest, ending with the current password.
  Each put() call produces a genuine 1Password history entry, visible in the
  UI via "View password history". Items with no history are bulk-created
  normally. Dates are not preserved (1Password history timestamps reflect
  when the import ran).

ATTACHMENTS
  Binary attachments stored in <Binary> elements are imported as 1Password
  file attachments. KeePass stores them base64-encoded inside the XML.

RESUMABILITY
  On interruption (e.g. rate-limit / 429) a state file is written next to the
  input file. Re-running the same command resumes automatically.

REQUIREMENTS
  - OP_SERVICE_ACCOUNT_TOKEN env var
  - onepassword-sdk  (auto-installed into .venv-1pw if missing)

USAGE
  python import-from-keepass-xml.py \\
    --input keepass-export.xml \\
    --vault "KeePass Import" \\
    [--dry-run] \\
    [--silent]
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
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Auto-install: create a venv next to this script if the SDK is missing.
# ---------------------------------------------------------------------------
try:
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
        print(
            "ERROR: onepassword-sdk failed to import even inside the venv.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isfile(_venv_python):
        print(f"Creating virtual environment at {_venv_dir}...")
        _venv.create(_venv_dir, with_pip=True)

    _req_file = os.path.join(_script_dir, "requirements.txt")
    if os.path.isfile(_req_file):
        print(f"Installing packages from {_req_file}...")
        _sp.check_call(
            [_venv_python, "-m", "pip", "install", "--quiet", "-r", _req_file]
        )
    else:
        print("Installing onepassword-sdk...")
        _sp.check_call(
            [_venv_python, "-m", "pip", "install", "--quiet", "onepassword-sdk"]
        )

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


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PasswordHistoryEntry:
    """A single historical password with its last-modification timestamp."""

    timestamp: str  # ISO-8601 string from KeePass <LastModificationTime>
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
    group_path: List[str]  # e.g. ["Email", "Work"]
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
        print(
            f"WARN: Could not read state file {path}: {e}. Starting fresh.",
            file=sys.stderr,
        )
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
    data = {
        "checksum": _compute_checksum(fingerprints),
        "completed": fingerprints,
        "count": len(fingerprints),
    }
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


def _parse_history(
    entry_el: ET.Element, current_password: Optional[str]
) -> List[PasswordHistoryEntry]:
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


def _parse_attachments(
    entry_el: ET.Element, binary_pool: Dict[str, bytes]
) -> List[InMemoryAttachment]:
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
                print(
                    f"WARN: attachment ref {ref!r} ('{name}') not found in binary pool",
                    file=sys.stderr,
                )
                continue
        else:
            # Inline base64
            raw = (val_el.text or "").strip()
            if not raw:
                continue
            try:
                content = base64.b64decode(raw)
            except Exception as e:
                print(
                    f"WARN: could not decode attachment '{name}': {e}", file=sys.stderr
                )
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
            print(
                f"WARN: could not decode binary pool entry id={ref_id}: {e}",
                file=sys.stderr,
            )
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

        title = _find_string_value(entry_el, "Title") or "Untitled"
        login = _find_string_value(entry_el, "UserName") or None
        password = _find_string_value(entry_el, "Password") or None
        url = _find_string_value(entry_el, "URL") or None
        notes = _find_string_value(entry_el, "Notes") or None
        otpauth = _extract_otpauth(entry_el)

        # Suppress the otpauth string from appearing raw in notes
        if notes and otpauth and otpauth in notes:
            notes = notes.replace(otpauth, "").strip() or None

        history = _parse_history(entry_el, password)
        attachments = _parse_attachments(entry_el, binary_pool)

        records.append(
            Record(
                title=title,
                login=login,
                password=password,
                login_url=url,
                notes=notes,
                otpauth=otpauth,
                group_path=current_path,
                attachments=attachments,
                password_history=history,
            )
        )

    # Recurse into sub-groups
    for sub_group in group_el.findall("Group"):
        _walk_group(
            sub_group,
            current_path,
            binary_pool,
            records,
            skip_recycle_bin=skip_recycle_bin,
        )


def load_keepass_xml(input_path: str) -> List[Record]:
    """Parse a KeePass XML 2.x export file and return a flat list of Records."""
    try:
        tree = ET.parse(input_path)
    except ET.ParseError as e:
        print(f"ERROR: Failed to parse XML: {e}", file=sys.stderr)
        sys.exit(2)

    root = tree.getroot()
    if root.tag != "KeePassFile":
        print(
            f"ERROR: Expected root tag <KeePassFile>, got <{root.tag}>. "
            "Is this a KeePass XML 2.x export?",
            file=sys.stderr,
        )
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
        title = _find_string_value(entry_el, "Title") or "Untitled"
        login = _find_string_value(entry_el, "UserName") or None
        password = _find_string_value(entry_el, "Password") or None
        url = _find_string_value(entry_el, "URL") or None
        notes = _find_string_value(entry_el, "Notes") or None
        otpauth = _extract_otpauth(entry_el)
        if notes and otpauth and otpauth in notes:
            notes = notes.replace(otpauth, "").strip() or None
        history = _parse_history(entry_el, password)
        attachments = _parse_attachments(entry_el, binary_pool)
        records.append(
            Record(
                title=title,
                login=login,
                password=password,
                login_url=url,
                notes=notes,
                otpauth=otpauth,
                group_path=[],  # top-level items have no group path
                attachments=attachments,
                password_history=history,
            )
        )

    for sub_group in root_group.findall("Group"):
        _walk_group(sub_group, [], binary_pool, records)

    return records


# ---------------------------------------------------------------------------
# Notes field builder
# ---------------------------------------------------------------------------


def _build_notes(rec: Record) -> Optional[str]:
    """Return the item's original notes, unmodified. History is written via put()."""
    return rec.notes or None


# ---------------------------------------------------------------------------
# Tag derivation from group path
# ---------------------------------------------------------------------------


def _group_path_to_tags(group_path: List[str]) -> List[str]:
    """
    Convert a KeePass group path to a list of 1Password tags.

    Each level of the hierarchy gets its own tag so items are findable
    by either the top-level group or the full path:
      ["Email"]        → ["Email"]
      ["Email", "Work"] → ["Email", "Email/Work"]
    Items at the database root (empty path) receive no tags.
    """
    tags: List[str] = []
    for i in range(len(group_path)):
        tags.append("/".join(group_path[: i + 1]))
    return tags


# ---------------------------------------------------------------------------
# ItemCreateParams builders
# ---------------------------------------------------------------------------

BULK_CREATE_MAX = 100


def _chunked(items: List, size: int) -> List[List]:
    return [items[i : i + size] for i in range(0, len(items), size)]


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
    *,
    password_override: Optional[str] = None,
) -> ItemCreateParams:
    fields: List[ItemField] = []
    password_value = (
        password_override if password_override is not None else rec.password
    )
    if rec.login is not None:
        fields.append(
            ItemField(
                id="username",
                value=rec.login,
                title="Username",
                fieldType=ItemFieldType.TEXT,
            )
        )
    if password_value is not None:
        fields.append(
            ItemField(
                id="password",
                value=password_value,
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

    files = _make_file_params(rec.attachments, sections)

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


def _set_password_on_item(item, password: str) -> None:
    """Mutate a live 1Password item object's password field value in place."""
    for f in item.fields or []:
        if getattr(f, "id", None) == "password":
            f.value = password
            return
    # Field not found — nothing to mutate (item has no password field)


async def _replay_history(client, item, rec: Record, *, silent: bool) -> bool:
    """
    Replay KeePass password history as real 1Password item history.

    Each put() causes 1Password to save the *previous* live value into history.
    To produce history [A, B, C] with current password D (D not in history):

      create(A)  →  put(B)  →  put(C)  →  put(D)
                    saves A     saves B     saves C
                    to hist     to hist     to hist

    The item is already created with the oldest password (A) by the caller,
    so we just put() each subsequent value in order, ending with the current.

    Returns True on success, False if rate-limited.
    """
    if not rec.password_history:
        return True

    # history is newest-first; reverse to oldest-first, skip the first entry
    # (oldest) because the item was already created with that value.
    oldest_first = list(reversed(rec.password_history))

    for h in oldest_first[1:]:
        _set_password_on_item(item, h.password)
        try:
            item = await client.items.put(item)
        except Exception as e:
            if _is_rate_limit_error(e):
                return False
            print(
                f"WARN: failed to write history entry for '{rec.title}': {e}",
                file=sys.stderr,
            )
            return True  # non-fatal: skip remaining history for this item

    # Final put() sets the current password as the live value.
    # This saves the last historical password (C) into history, not D.
    _set_password_on_item(item, rec.password or "")
    try:
        await client.items.put(item)
    except Exception as e:
        if _is_rate_limit_error(e):
            return False
        print(
            f"WARN: failed to restore current password for '{rec.title}': {e}",
            file=sys.stderr,
        )
    return True


async def plan_and_apply(
    records: List[Record],
    *,
    input_path: str,
    vault_name: str,
    dry: bool,
    silent: bool,
) -> None:
    client = await _get_client()
    completed = load_state(input_path, silent=silent) if not dry else set()

    # Ensure the single destination vault exists (create if needed)
    name_to_id, _ = await _vault_name_to_id_map(client)
    vault_id = await _ensure_vault(
        client, vault_name, name_to_id, dry=dry, silent=silent
    )

    if dry:
        for rec in records:
            tags = _group_path_to_tags(rec.group_path)
            category = _categorize(rec)
            hist_count = len(rec.password_history)
            att_names = [a.name for a in rec.attachments]
            msg = f"DRY-RUN: {category.upper()} '{rec.title}' → vault '{vault_name}'"
            if tags:
                msg += f" tags={tags}"
            if rec.otpauth:
                msg += " +TOTP"
            if hist_count:
                msg += f" +{hist_count} history put() calls"
            if att_names:
                msg += f" +files {att_names}"
            print(msg)
        return

    # Split records into two groups:
    #   - no_history: eligible for bulk create_all (fast path)
    #   - with_history: must be created individually then put() N times
    no_history: List[_PendingItem] = []
    with_history: List[_PendingItem] = []
    skipped = 0

    for rec in records:
        fp = _item_fingerprint(vault_id, rec)
        if fp in completed:
            skipped += 1
            continue

        tags = _group_path_to_tags(rec.group_path) or None
        notes = _build_notes(rec)
        category = _categorize(rec)

        if rec.password_history:
            # Create with the oldest historical password (A). Each subsequent
            # put() then shifts the window: put(B) saves A, put(C) saves B,
            # put(D) saves C — so history ends up as [A, B, C] and D is live.
            oldest_password = rec.password_history[-1].password  # list is newest-first
            if category == "Login":
                params = _build_login_params(
                    vault_id, rec, notes, tags, password_override=oldest_password
                )
            else:
                params = _build_secure_note_params(vault_id, rec, notes, tags)
            with_history.append(_PendingItem(params=params, fingerprint=fp, rec=rec))
        else:
            if category == "Login":
                params = _build_login_params(vault_id, rec, notes, tags)
            else:
                params = _build_secure_note_params(vault_id, rec, notes, tags)
            no_history.append(_PendingItem(params=params, fingerprint=fp, rec=rec))

    if skipped and not silent:
        print(f"⏭  Skipping {skipped} already-completed items")

    total_remaining = len(no_history) + len(with_history)
    if total_remaining == 0:
        if not silent:
            print("✔ All items already imported — nothing to do")
        delete_state(input_path, silent=silent)
        return

    if not silent:
        print(
            f"📦 {total_remaining} items to create in vault '{vault_name}'"
            + (f" ({len(with_history)} with history replay)" if with_history else "")
        )

    rate_limited = False
    total_ok = 0

    # ── Fast path: bulk create items with no history ──────────────────────────
    for chunk in _chunked(no_history, BULK_CREATE_MAX):
        if rate_limited:
            break
        try:
            resp: ItemsUpdateAllResponse = await client.items.create_all(
                vault_id, [item.params for item in chunk]
            )
        except Exception as e:
            if _is_rate_limit_error(e):
                print(
                    f"\n⚠  Rate limited during bulk create. Saving progress...",
                    file=sys.stderr,
                )
                rate_limited = True
                break
            print(f"ERROR bulk create in vault '{vault_name}': {e}", file=sys.stderr)
            continue

        for i, ir in enumerate(resp.individual_responses):
            if ir.error is not None:
                err_str = str(ir.error).lower()
                if "429" in err_str or "rate limit" in err_str:
                    print(
                        f"\n⚠  Rate limited on item '{chunk[i].rec.title}'. Saving progress...",
                        file=sys.stderr,
                    )
                    rate_limited = True
                    break
                print(
                    f"ERROR creating '{chunk[i].params.title}': {ir.error}",
                    file=sys.stderr,
                )
            else:
                completed.add(chunk[i].fingerprint)
                total_ok += 1

    # ── Slow path: create + put() for items that have history ─────────────────
    for pending in with_history:
        if rate_limited:
            break
        try:
            item = await client.items.create(pending.params)
        except Exception as e:
            if _is_rate_limit_error(e):
                print(
                    f"\n⚠  Rate limited creating '{pending.rec.title}'. Saving progress...",
                    file=sys.stderr,
                )
                rate_limited = True
                break
            print(f"ERROR creating '{pending.rec.title}': {e}", file=sys.stderr)
            continue

        ok = await _replay_history(client, item, pending.rec, silent=silent)
        if not ok:
            print(
                f"\n⚠  Rate limited replaying history for '{pending.rec.title}'. Saving progress...",
                file=sys.stderr,
            )
            rate_limited = True
            break

        completed.add(pending.fingerprint)
        total_ok += 1
        if not silent:
            hist_count = len(pending.rec.password_history)
            print(
                f"  ✔ '{pending.rec.title}' created with {hist_count} history entries"
            )

    if not silent:
        print(f"✔ Created {total_ok}/{total_remaining} items in vault '{vault_name}'")

    if rate_limited:
        save_state(input_path, completed, silent=silent)
        print(
            "\n🔄 Import paused due to rate limiting. Re-run the same command to resume.",
            file=sys.stderr,
        )
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
        description="KeePass XML → 1Password migration (single vault, group paths as tags)"
    )
    ap.add_argument(
        "--input", required=True, help="Path to KeePass XML 2.x export (.xml)"
    )
    ap.add_argument(
        "--vault",
        required=True,
        help="Destination vault name (created if it does not exist)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without creating anything",
    )
    ap.add_argument("--silent", action="store_true", help="Suppress progress output")

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
        att_count = sum(len(r.attachments) for r in records)
        hist_count = sum(len(r.password_history) for r in records)
        print(
            f"Loaded {len(records)} entries"
            + (f" ({att_count} attachments)" if att_count else "")
            + (
                f" ({hist_count} historical passwords across all entries)"
                if hist_count
                else ""
            )
        )

    await plan_and_apply(
        records,
        input_path=os.path.abspath(args.input),
        vault_name=args.vault,
        dry=args.dry_run,
        silent=args.silent,
    )


if __name__ == "__main__":
    asyncio.run(main())
