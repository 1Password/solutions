#!/usr/bin/env python3
"""
keepass_to_1password.py
========================

Parse a Pleasant Password Server XML export and import it straight into
1Password using the official 1Password Python SDK (`onepassword-sdk` on PyPI),
in one step.

- Every Pleasant Password Server Group that directly contains entries becomes
  one 1Password vault. The vault is named "<leaf folder> - <parent folder>"
  (e.g. a path of .../JAG/Client 1 becomes the vault "Client 1 - JAG").
  Top-level groups with no parent just use their own name.
- Every export Entry is mapped to the closest matching 1Password item
  category (Login, Secure Note, Credit Card, Identity, SSH Key, Password,
  Document, etc.) using the entry's field names as signals. See
  README.md for how the classifier works and its limitations.

Setup
-----
    pip install -r requirements.txt

Authenticate with either a service account token or your signed-in
1Password desktop app (Settings → Developer → Integrate with other apps):

    export OP_SERVICE_ACCOUNT_TOKEN="ops_..."   # service account
    # or
    export OP_ACCOUNT_NAME="My Team"            # desktop app account name (sidebar label)

Usage
-----
    python keepass_to_1password.py Export.xml
    python keepass_to_1password.py Export.xml --dry-run
    python keepass_to_1password.py Export.xml --account "My Team"
    python keepass_to_1password.py Sample_Export.xml --dry-run   # try it on the bundled sample first
    python keepass_to_1password.py Export.xml --log-file Export.pps-import.json
    python keepass_to_1password.py --delete-import Export.pps-import.json
    python keepass_to_1password.py Export.xml --delete-import   # uses ./Export.pps-import.json
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import gzip
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# Pleasant Password Server XML parsing (KeePass XML 2.x format)
# --------------------------------------------------------------------------

def normalize_key(key: str) -> str:
    """'Card Number' -> 'cardnumber' so we can match field names loosely."""
    return re.sub(r"[^a-z0-9]", "", key.lower())


def text_of(el, tag, default=""):
    child = el.find(tag)
    if child is None or child.text is None:
        return default
    return child.text


def parse_binaries(root) -> Dict[str, bytes]:
    """Return {binary_id: raw bytes} from Meta/Binaries, decompressing gzip
    payloads when Compressed="True", as KeePass XML 2.x exports do."""
    binaries = {}
    for bin_el in root.findall("./Meta/Binaries/Binary"):
        bin_id = bin_el.get("ID")
        if bin_id is None or bin_el.text is None:
            continue
        raw = base64.b64decode(bin_el.text)
        if bin_el.get("Compressed", "False").lower() == "true":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass  # leave as-is if it isn't actually gzip
        binaries[bin_id] = raw
    return binaries


def parse_entry(entry_el, binaries: Dict[str, bytes]) -> dict:
    fields = {}
    for string_el in entry_el.findall("String"):
        key_el = string_el.find("Key")
        val_el = string_el.find("Value")
        if key_el is None:
            continue
        key = key_el.text or ""
        value = val_el.text if val_el is not None and val_el.text is not None else ""
        fields[key] = value

    attachments = []
    for bin_el in entry_el.findall("Binary"):
        fname = text_of(bin_el, "Key", "attachment")
        value_el = bin_el.find("Value")
        ref = value_el.get("Ref") if value_el is not None else None
        if ref is not None and ref in binaries:
            attachments.append({"name": fname, "content": binaries[ref]})

    return {
        "raw_fields": fields,          # original export String key -> value
        "attachments": attachments,    # [{name, content bytes}]
    }


def walk_group(group_el, path: List[str], binaries, vaults: dict):
    name = text_of(group_el, "Name", "(unnamed)")
    current_path = path + [name]

    entries = [parse_entry(e, binaries) for e in group_el.findall("Entry")]
    if entries:
        key = " / ".join(current_path)
        vaults[key]["path"] = current_path
        vaults[key]["entries"].extend(entries)

    for sub in group_el.findall("Group"):
        walk_group(sub, current_path, binaries, vaults)


def vault_title_for(path: List[str]) -> str:
    """'Last path value - second last value', e.g. .../JAG/Client 1 -> 'Client 1 - JAG'."""
    if len(path) >= 2:
        return f"{path[-1]} - {path[-2]}"
    return path[-1]


def disambiguate_titles(vaults: dict):
    """If two different folders would produce the same 'leaf - parent' title,
    extend with more of the path (grandparent, etc.) until unique."""
    def title_at_depth(path, depth):
        segment = path[-depth:] if depth <= len(path) else path[:]
        if len(segment) >= 2:
            return f"{segment[-1]} - {' / '.join(reversed(segment[:-1]))}"
        return segment[-1]

    depth = 2
    while True:
        seen = defaultdict(list)
        for v in vaults.values():
            seen[title_at_depth(v["path"], depth)].append(v)
        if all(len(vs) == 1 for vs in seen.values()):
            for title, vs in seen.items():
                vs[0]["vault_title"] = title
            return
        max_len = max(len(v["path"]) for v in vaults.values())
        if depth >= max_len:
            # last resort: fully qualify, plus a numeric suffix for exact dupes
            counts = defaultdict(int)
            for v in vaults.values():
                full = " / ".join(v["path"])
                counts[full] += 1
                v["vault_title"] = full if counts[full] == 1 else f"{full} ({counts[full]})"
            return
        depth += 1


def parse_pps_xml(xml_path: str) -> List[dict]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    root_group = root.find("Root/Group")
    if root_group is None:
        print("Could not find Root/Group in the XML file.", file=sys.stderr)
        sys.exit(1)

    binaries = parse_binaries(root)
    vaults = defaultdict(lambda: {"path": [], "entries": []})
    walk_group(root_group, [], binaries, vaults)
    disambiguate_titles(vaults)
    return list(vaults.values())


# --------------------------------------------------------------------------
# Export entry -> 1Password category classifier
# --------------------------------------------------------------------------
# Pleasant Password Server exports have no native concept of "item type" -
# every entry is just a bag of Title/UserName/Password/URL/Notes plus arbitrary
# custom String fields. To recover something like 1Password's item categories,
# we look for field-name signatures commonly attached to export entries
# (e.g. "Card Number" + "CVV" strongly implies a credit card). This is a
# best-effort heuristic, not a guarantee - see README.md.

# Each rule: (category name, {normalized field-name signals}, min matches needed)
CATEGORY_RULES = [
    ("Document",             set(), 0),   # handled separately (has attachment)
    ("SshKey",               {"sshprivatekey"}, 1),
    ("CryptoWallet",         {"walletaddress", "recoveryphrase", "seedphrase", "privatekeywif", "cryptocurrency"}, 1),
    ("CreditCard",           {"cardnumber", "cvv", "cardholdername", "cardtype"}, 1),
    ("BankAccount",          {"accountnumber", "routingnumber", "iban", "bankname"}, 1),
    ("SocialSecurityNumber", {"ssn", "socialsecuritynumber"}, 1),
    ("Passport",             {"passportnumber", "nationality"}, 1),
    ("DriverLicense",        {"licensenumber", "licensestate", "licenseclass"}, 1),
    ("SoftwareLicense",      {"licensekey", "serialnumber", "licensedto"}, 1),
    ("OutdoorLicense",       {"permitnumber", "huntingseason", "gamezone"}, 1),
    ("MedicalRecord",        {"bloodtype", "policynumber", "physicianname", "medicalconditions"}, 1),
    ("Membership",           {"membershipnumber", "membershiplevel"}, 1),
    ("Rewards",              {"rewardsnumber", "pointsbalance", "tierstatus"}, 1),
    ("ApiCredentials",       {"apikey", "clientid", "clientsecret", "accesstoken"}, 1),
    ("Database",             {"databasename", "hostname", "port"}, 2),
    ("Server",               {"ipaddress", "osversion", "servername"}, 1),
    ("Router",               {"ssid", "wifipassword", "routeradminurl"}, 1),
    ("Identity",             {"firstname", "lastname", "dateofbirth", "address", "city"}, 2),
    ("Email",                {"imapserver", "pop3server", "smtpserver", "emailaddress"}, 1),
    ("Person",               {"fullname", "relationship"}, 1),
]

DOCUMENT_KEY_HINTS = {"filename", "attachment", "document"}


def classify_entry(fields: dict, attachments: list) -> str:
    if attachments:
        return "Document"

    normalized = {normalize_key(k) for k in fields.keys() if fields.get(k)}

    for category, signals, min_matches in CATEGORY_RULES:
        if category == "Document":
            continue
        if signals and len(normalized & signals) >= min_matches:
            # The SDK rejects Person items outright ("bad request body"); preserve
            # contact fields on a Secure Note instead.
            if category == "Person":
                return "SecureNote"
            return category

    has_username = bool(fields.get("UserName"))
    has_password = bool(fields.get("Password"))
    has_url = bool(fields.get("URL"))
    has_notes = bool(fields.get("Notes"))

    if not has_username and not has_password and not has_url and has_notes:
        return "SecureNote"
    if has_password and not has_username:
        return "Password"
    return "Login"  # default fallback


# --------------------------------------------------------------------------
# 1Password field construction
# --------------------------------------------------------------------------

STANDARD_KEYS = {"Title", "UserName", "Password", "URL", "Notes"}
TOTP_KEYS = {"otp", "totp", "totpseed", "totpseedbase32"}

# normalized export field key -> (field id, display title, ItemFieldType member name)
# ItemFieldType member names are resolved against the SDK's actual enum at
# runtime so this table doubles as documentation of the mapping.
FIELD_TYPE_HINTS = {
    "cardnumber":        ("card_number", "card number", "CREDITCARDNUMBER"),
    "cardtype":           ("card_type", "card type", "CREDITCARDTYPE"),
    "cvv":                ("cvv", "verification number", "CONCEALED"),
    "expirationdate":     ("expiry", "expiry date", "MONTHYEAR"),
    "cardholdername":     ("cardholder", "cardholder name", "TEXT"),
    "walletaddress":      ("wallet_address", "wallet address", "TEXT"),
    "recoveryphrase":     ("recovery_phrase", "recovery phrase", "CONCEALED"),
    "seedphrase":         ("seed_phrase", "seed phrase", "CONCEALED"),
    "privatekeywif":      ("private_key", "private key", "CONCEALED"),
    "cryptocurrency":     ("currency", "currency", "TEXT"),
    "apikey":             ("api_key", "credential", "CONCEALED"),
    "clientid":           ("client_id", "client id", "TEXT"),
    "clientsecret":       ("client_secret", "client secret", "CONCEALED"),
    "accesstoken":        ("access_token", "access token", "CONCEALED"),
    "accountnumber":      ("account_number", "account number", "CONCEALED"),
    "routingnumber":      ("routing_number", "routing number", "TEXT"),
    "iban":               ("iban", "IBAN", "TEXT"),
    "bankname":           ("bank_name", "bank name", "TEXT"),
    "hostname":           ("hostname", "hostname", "TEXT"),
    "databasename":       ("database_name", "database", "TEXT"),
    "port":               ("port", "port", "TEXT"),
    "ipaddress":          ("ip_address", "IP address", "TEXT"),
    "osversion":          ("os_version", "operating system", "TEXT"),
    "servername":         ("server_name", "server name", "TEXT"),
    "ssid":               ("ssid", "network name (SSID)", "TEXT"),
    "wifipassword":       ("wifi_password", "Wi-Fi password", "CONCEALED"),
    "routeradminurl":     ("admin_url", "admin URL", "URL"),
    "licensenumber":      ("license_number", "license number", "CONCEALED"),
    "licensestate":       ("license_state", "issuing state/region", "TEXT"),
    "licenseclass":       ("license_class", "license class", "TEXT"),
    "passportnumber":     ("passport_number", "passport number", "CONCEALED"),
    "nationality":        ("nationality", "nationality", "TEXT"),
    "dateofissue":        ("date_of_issue", "date of issue", "TEXT"),
    "dateofexpiry":       ("date_of_expiry", "date of expiry", "TEXT"),
    "ssn":                ("ssn", "SSN", "CONCEALED"),
    "socialsecuritynumber": ("ssn", "SSN", "CONCEALED"),
    "licensekey":         ("license_key", "license key", "CONCEALED"),
    "serialnumber":       ("serial_number", "serial number", "TEXT"),
    "licensedto":         ("licensed_to", "licensed to", "TEXT"),
    "permitnumber":       ("permit_number", "permit number", "TEXT"),
    "huntingseason":      ("season", "season", "TEXT"),
    "gamezone":           ("zone", "zone", "TEXT"),
    "bloodtype":          ("blood_type", "blood type", "TEXT"),
    "policynumber":       ("policy_number", "policy number", "TEXT"),
    "physicianname":      ("physician", "physician", "TEXT"),
    "medicalconditions":  ("conditions", "conditions", "TEXT"),
    "membershipnumber":   ("membership_number", "membership number", "TEXT"),
    "membershiplevel":    ("membership_level", "membership level", "TEXT"),
    "rewardsnumber":      ("rewards_number", "rewards number", "TEXT"),
    "pointsbalance":      ("points_balance", "points balance", "TEXT"),
    "tierstatus":         ("tier_status", "tier status", "TEXT"),
    "firstname":          ("first_name", "first name", "TEXT"),
    "lastname":           ("last_name", "last name", "TEXT"),
    "dateofbirth":        ("date_of_birth", "date of birth", "TEXT"),
    "address":            ("address", "address", "TEXT"),
    "city":               ("city", "city", "TEXT"),
    "emailaddress":       ("email_address", "email address", "EMAIL"),
    "fullname":           ("full_name", "full name", "TEXT"),
    "relationship":       ("relationship", "relationship", "TEXT"),
    "phonenumber":        ("phone_number", "phone number", "PHONE"),
    "imapserver":         ("imap_server", "IMAP server", "TEXT"),
    "pop3server":         ("pop3_server", "POP3 server", "TEXT"),
    "smtpserver":         ("smtp_server", "SMTP server", "TEXT"),
    "keytype":            ("key_type", "key type", "TEXT"),
}

SECRET_HINT_WORDS = ("password", "secret", "key", "pin", "cvv", "ssn", "private", "token")


def build_item(sdk, category_name: str, entry: dict, vault_id: str):
    """Build an ItemCreateParams for one parsed export entry."""
    fields_raw = entry["raw_fields"]
    category = getattr(sdk.ItemCategory, category_name.upper())

    item_fields = []
    sections = []
    seen_normalized = set()

    title = fields_raw.get("Title", "").strip() or "(untitled)"
    notes = fields_raw.get("Notes") or None
    username = fields_raw.get("UserName") or ""
    password = fields_raw.get("Password") or ""
    url = fields_raw.get("URL") or ""

    # Login-style built-in fields for categories where a username/password
    # pairing makes sense.
    if category_name in ("Login", "Password") :
        if username:
            item_fields.append(sdk.ItemField(id="username", title="username",
                                              field_type=sdk.ItemFieldType.TEXT, value=username))
        if password:
            item_fields.append(sdk.ItemField(id="password", title="password",
                                              field_type=sdk.ItemFieldType.CONCEALED, value=password))
    elif username or password:
        # Other categories: still preserve username/password as plain fields
        # rather than dropping them, since export entries can mix a login
        # with category-specific fields.
        if username:
            item_fields.append(sdk.ItemField(id="username", title="username",
                                              field_type=sdk.ItemFieldType.TEXT, value=username))
        if password:
            item_fields.append(sdk.ItemField(id="password", title="password",
                                              field_type=sdk.ItemFieldType.CONCEALED, value=password))

    seen_normalized.update({"title", "notes", "username", "password", "url"})

    # TOTP
    totp_value = ""
    for key, value in fields_raw.items():
        if normalize_key(key) in TOTP_KEYS and value:
            totp_value = value
            break
    if totp_value:
        sections.append(sdk.ItemSection(id="totpsection", title="One-Time Password"))
        item_fields.append(sdk.ItemField(
            id="onetimepassword", title="one-time password",
            field_type=sdk.ItemFieldType.TOTP, section_id="totpsection", value=totp_value,
        ))
        seen_normalized.update({normalize_key(k) for k in TOTP_KEYS})

    # SSH private key -> dedicated SSHKEY field (SshKey category only)
    if category_name == "SshKey":
        for key, value in fields_raw.items():
            if normalize_key(key) == "sshprivatekey" and value:
                item_fields.append(sdk.ItemField(
                    id="private_key", title="private key",
                    field_type=sdk.ItemFieldType.SSHKEY, value=value,
                ))
                seen_normalized.add("sshprivatekey")
                break

    # Category-specific known fields, in a dedicated section
    known_section_added = False
    for key, value in fields_raw.items():
        if not value:
            continue
        norm = normalize_key(key)
        if norm in seen_normalized or key in STANDARD_KEYS:
            continue
        hint = FIELD_TYPE_HINTS.get(norm)
        if hint:
            field_id, field_title, type_name = hint
            if not known_section_added:
                sections.append(sdk.ItemSection(id="details", title="Details"))
                known_section_added = True
            field_type = getattr(sdk.ItemFieldType, type_name, sdk.ItemFieldType.TEXT)
            item_fields.append(sdk.ItemField(
                id=field_id, title=field_title, field_type=field_type,
                section_id="details", value=value,
            ))
            seen_normalized.add(norm)

    # Anything left over: dump into an "Export metadata" section so nothing
    # is silently lost, guessing CONCEALED vs TEXT from the key name.
    leftover_added = False
    for i, (key, value) in enumerate(fields_raw.items()):
        norm = normalize_key(key)
        if key in STANDARD_KEYS or norm in seen_normalized or not value:
            continue
        if not leftover_added:
            sections.append(sdk.ItemSection(id="pps_meta", title="Export metadata"))
            leftover_added = True
        is_secret = any(w in norm for w in SECRET_HINT_WORDS)
        item_fields.append(sdk.ItemField(
            id=f"kp_{i}", title=key,
            field_type=sdk.ItemFieldType.CONCEALED if is_secret else sdk.ItemFieldType.TEXT,
            section_id="pps_meta", value=str(value),
        ))

    websites = None
    if url and category_name in ("Login", "Password"):
        websites = [sdk.Website(url=url, label="website",
                                 autofill_behavior=sdk.AutofillBehavior.ANYWHEREONWEBSITE)]
    elif url:
        # keep the URL even for categories that don't support autofill websites
        item_fields.append(sdk.ItemField(id="url", title="URL",
                                          field_type=sdk.ItemFieldType.URL, value=url))

    document = None
    if category_name == "Document":
        if entry["attachments"]:
            att = entry["attachments"][0]  # Document items hold a single primary file
            document = sdk.DocumentCreateParams(name=att["name"], content=att["content"])
            if len(entry["attachments"]) > 1:
                extra = ", ".join(a["name"] for a in entry["attachments"][1:])
                notes = (notes or "") + f"\n\n[Additional export attachments not imported: {extra}]"
        else:
            notes = (notes or "") + "\n\n[Classified as Document but no attachment was found in the export.]"
            category = sdk.ItemCategory.SECURENOTE
            category_name = "SecureNote"

    kwargs = dict(
        title=title,
        category=category,
        vault_id=vault_id,
        fields=item_fields or None,
        sections=sections or None,
        notes=notes,
        websites=websites,
    )
    if document:
        kwargs["document"] = document

    return sdk.ItemCreateParams(**kwargs)


def _ssh_key_import_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "private key" in msg or "ssh key" in msg or "openssh" in msg


def _document_import_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "document" in msg and ("file" in msg or "attach" in msg)


def _structured_item_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "bad request body" in msg or "bad input passed by the user" in msg


async def create_item(client, sdk, category_name: str, entry: dict, vault_id: str, item_title: str):
    """Create an item, with Secure Note fallbacks for unparseable SSH keys or documents."""
    params = build_item(sdk, category_name, entry, vault_id)
    try:
        created = await client.items.create(params)
        return created, category_name
    except Exception as exc:
        note = entry["raw_fields"].get("Notes") or ""
        if category_name == "SshKey" and _ssh_key_import_error(exc):
            print(
                f"  warning: could not parse SSH key for {item_title!r} ({exc}); "
                "saving as Secure Note with concealed key text",
                file=sys.stderr,
            )
            fallback_note = (
                f"{note}\n\n[SSH key could not be imported as a native SSH Key item; "
                "stored as concealed text instead.]"
            ).strip()
        elif category_name == "Document" and _document_import_error(exc):
            att_names = ", ".join(a["name"] for a in entry["attachments"]) or "(unknown)"
            print(
                f"  warning: could not attach document for {item_title!r} ({exc}); "
                "saving as Secure Note",
                file=sys.stderr,
            )
            fallback_note = (
                f"{note}\n\n[Document attachment(s) could not be imported: {att_names}.]"
            ).strip()
        elif _structured_item_error(exc):
            print(
                f"  warning: could not create {category_name} item {item_title!r} ({exc}); "
                "saving as Secure Note",
                file=sys.stderr,
            )
            fallback_note = (
                f"{note}\n\n[{category_name} item could not be created via the SDK; "
                "stored as a Secure Note instead.]"
            ).strip()
        else:
            raise

        fallback_entry = {
            **entry,
            "raw_fields": {**entry["raw_fields"], "Notes": fallback_note},
            "attachments": [],
        }
        params = build_item(sdk, "SecureNote", fallback_entry, vault_id)
        created = await client.items.create(params)
        return created, "SecureNote"


# --------------------------------------------------------------------------
# 1Password import
# --------------------------------------------------------------------------

def resolve_auth(account_arg: Optional[str] = None):
    """Return a service account token or DesktopAuth for Client.authenticate()."""
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    account = account_arg or os.environ.get("OP_ACCOUNT_NAME")

    if token and account:
        print(
            "Set either OP_SERVICE_ACCOUNT_TOKEN or OP_ACCOUNT_NAME/--account, not both.",
            file=sys.stderr,
        )
        sys.exit(1)
    if token:
        return token
    if account:
        from onepassword import DesktopAuth
        return DesktopAuth(account_name=account)

    print(
        "No 1Password credentials found. Set OP_SERVICE_ACCOUNT_TOKEN for a service "
        "account, or OP_ACCOUNT_NAME (or --account) for desktop app auth.",
        file=sys.stderr,
    )
    print(
        "Desktop auth requires the 1Password app with "
        "Settings → Developer → Integrate with other apps enabled.",
        file=sys.stderr,
    )
    sys.exit(1)


class SdkHandles:
    """Small bag of references to the imported SDK names, so build_item()
    doesn't need a dozen separate imports passed around."""
    def __init__(self):
        from onepassword import (
            AutofillBehavior, Client, DesktopAuth, DocumentCreateParams, ItemCategory,
            ItemCreateParams, ItemField, ItemFieldType, ItemSection, VaultCreateParams,
            VaultListParams, Website,
        )

        self.Client = Client
        self.DesktopAuth = DesktopAuth
        self.AutofillBehavior = AutofillBehavior
        self.DocumentCreateParams = DocumentCreateParams
        self.ItemCategory = ItemCategory
        self.ItemCreateParams = ItemCreateParams
        self.ItemField = ItemField
        self.ItemFieldType = ItemFieldType
        self.ItemSection = ItemSection
        self.VaultCreateParams = VaultCreateParams
        self.VaultListParams = VaultListParams
        self.Website = Website


async def get_or_create_vault(client, sdk, title, dry_run):
    if not dry_run:
        existing = await client.vaults.list(sdk.VaultListParams(decrypt_details=True))
        for v in existing:
            if v.title == title:
                print(f"  vault {title!r} already exists (id={v.id}); reusing it")
                return v.id, False

    if dry_run:
        print(f"  [dry-run] would create/reuse vault {title!r}")
        return f"DRY-RUN-VAULT-ID:{title}", True

    params = sdk.VaultCreateParams(
        title=title, description="Imported from Pleasant Password Server export",
    )
    created = await client.vaults.create(params)
    print(f"  created vault {title!r} (id={created.id})")
    return created.id, True


def default_log_path(xml_file: str) -> str:
    """Default log path in the current working directory, named after the export file."""
    stem = Path(xml_file).name
    if stem.lower().endswith(".xml"):
        stem = stem[:-4]
    return str(Path.cwd() / f"{stem}.pps-import.json")


def resolve_log_path(args) -> str:
    if args.log_file:
        return str(Path(args.log_file).resolve())
    if args.xml_file:
        return default_log_path(args.xml_file)
    return ""


def new_import_log(xml_file: str) -> dict[str, Any]:
    return {
        "source_xml": str(Path(xml_file).resolve()),
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "vaults": [],
        "failures": [],
    }


def append_vault_log(import_log: dict[str, Any], *, title: str, vault_id: str, created: bool) -> dict[str, Any]:
    vault_log = {"title": title, "id": vault_id, "created": created, "items": []}
    import_log["vaults"].append(vault_log)
    return vault_log


def write_import_log(path: str, import_log: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(import_log, f, indent=2)
        f.write("\n")
    print(f"\nImport log written to {path}")


async def delete_import(args):
    log_path = resolve_log_path(args)
    if not log_path:
        print("Provide --log-file or an xml_file to locate the import log.", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(log_path):
        print(f"Import log not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    with open(log_path, encoding="utf-8") as f:
        import_log = json.load(f)

    vaults = import_log.get("vaults") or []
    if not vaults:
        print(f"No vaults recorded in {log_path}; nothing to delete.")
        return

    created_vaults = [v for v in vaults if v.get("created")]
    reused_vaults = [v for v in vaults if not v.get("created")]
    reused_items = sum(len(v.get("items") or []) for v in reused_vaults)

    print(f"Import log: {log_path}")
    print(f"  source: {import_log.get('source_xml', '(unknown)')}")
    print(f"  imported at: {import_log.get('imported_at', '(unknown)')}")
    print(f"  vaults to delete: {len(created_vaults)}")
    print(f"  items to delete from reused vaults: {reused_items}")

    if args.dry_run:
        for vault in created_vaults:
            print(f"  [dry-run] would delete vault {vault['title']!r} (id={vault['id']})")
        for vault in reused_vaults:
            for item in vault.get("items") or []:
                print(
                    f"  [dry-run] would delete item {item['title']!r} "
                    f"(id={item['id']}) from reused vault {vault['title']!r}"
                )
        return

    try:
        sdk = SdkHandles()
    except ImportError as exc:
        print(f"Could not import onepassword-sdk: {exc}", file=sys.stderr)
        sys.exit(1)

    auth = resolve_auth(args.account)
    auth_label = "service account" if isinstance(auth, str) else f"desktop app ({auth.account_name})"
    print(f"Authenticating via {auth_label}...")
    client = await sdk.Client.authenticate(
        auth=auth,
        integration_name="Pleasant Password Server Import Script",
        integration_version="1.0.0",
    )

    deleted_vaults = 0
    deleted_items = 0
    for vault in created_vaults:
        vault_id = vault.get("id")
        if not vault_id or str(vault_id).startswith("DRY-RUN-"):
            continue
        try:
            await client.vaults.delete(vault_id)
            print(f"  deleted vault {vault['title']!r} (id={vault_id})")
            deleted_vaults += 1
        except Exception as exc:
            print(f"  failed to delete vault {vault['title']!r}: {exc}", file=sys.stderr)

    for vault in reused_vaults:
        vault_id = vault.get("id")
        if not vault_id or str(vault_id).startswith("DRY-RUN-"):
            continue
        for item in vault.get("items") or []:
            item_id = item.get("id")
            if not item_id:
                continue
            try:
                await client.items.delete(vault_id, item_id)
                print(
                    f"  deleted item {item['title']!r} (id={item_id}) "
                    f"from reused vault {vault['title']!r}"
                )
                deleted_items += 1
            except Exception as exc:
                print(
                    f"  failed to delete item {item['title']!r} from {vault['title']!r}: {exc}",
                    file=sys.stderr,
                )

    print(f"\nCleanup complete. Deleted {deleted_vaults} vault(s) and {deleted_items} item(s).")
    if deleted_vaults == len(created_vaults) and deleted_items == reused_items:
        try:
            os.remove(log_path)
            print(f"Removed import log {log_path}")
        except OSError as exc:
            print(f"Could not remove import log: {exc}", file=sys.stderr)


async def run(args):
    vaults_data = parse_pps_xml(args.xml_file)

    total_entries = sum(len(v["entries"]) for v in vaults_data)
    print(f"Parsed {len(vaults_data)} vault(s) / {total_entries} entrie(s) from {args.xml_file}")
    preview_category_counts = defaultdict(int)
    for v in vaults_data:
        print(f"  - {v['vault_title']!r}: {len(v['entries'])} item(s)")
        if args.list_only:
            for entry in v["entries"]:
                cat = classify_entry(entry["raw_fields"], entry["attachments"])
                preview_category_counts[cat] += 1
                title = entry["raw_fields"].get("Title", "(untitled)")
                print(f"      [{cat}] {title}")
    print()

    if args.list_only:
        print("Category breakdown:")
        for cat, count in sorted(preview_category_counts.items()):
            print(f"  {cat}: {count}")
        return

    try:
        sdk = SdkHandles()
    except ImportError as exc:
        print(f"Could not import onepassword-sdk: {exc}", file=sys.stderr)
        print("Install or upgrade with: pip install -r requirements.txt",
              file=sys.stderr)
        sys.exit(1)

    client = None
    if not args.dry_run:
        auth = resolve_auth(args.account)
        auth_label = "service account" if isinstance(auth, str) else f"desktop app ({auth.account_name})"
        print(f"Authenticating via {auth_label}...")
        client = await sdk.Client.authenticate(
            auth=auth,
            integration_name="Pleasant Password Server Import Script",
            integration_version="1.0.0",
        )

    total_items = 0
    category_counts = defaultdict(int)
    import_log = None if args.dry_run else new_import_log(args.xml_file)
    log_path = resolve_log_path(args) if import_log is not None else ""

    for vault_entry in vaults_data:
        title = vault_entry["vault_title"]
        entries = vault_entry["entries"]
        print(f"Vault: {title} ({len(entries)} item(s))")

        vault_id, vault_created = await get_or_create_vault(client, sdk, title, args.dry_run)
        vault_log = None
        if import_log is not None:
            vault_log = append_vault_log(
                import_log, title=title, vault_id=vault_id, created=vault_created,
            )

        for entry in entries:
            category_name = classify_entry(entry["raw_fields"], entry["attachments"])
            category_counts[category_name] += 1
            item_title = entry["raw_fields"].get("Title", "(untitled)")

            if args.dry_run:
                print(f"  [dry-run] would create {category_name} item {item_title!r}")
                total_items += 1
                continue

            try:
                created, actual_category = await create_item(
                    client, sdk, category_name, entry, vault_id, item_title,
                )
                if actual_category != category_name:
                    category_counts[category_name] -= 1
                    category_counts[actual_category] += 1
                print(f"  created {actual_category} item {created.title!r} (id={created.id})")
                total_items += 1
                if vault_log is not None:
                    vault_log["items"].append({
                        "title": created.title,
                        "id": created.id,
                        "category": actual_category,
                        "planned_category": category_name,
                    })
            except Exception as exc:
                print(
                    f"  failed to create {category_name} item {item_title!r}: {exc}",
                    file=sys.stderr,
                )
                if import_log is not None:
                    import_log["failures"].append({
                        "vault_title": title,
                        "vault_id": vault_id,
                        "item_title": item_title,
                        "category": category_name,
                        "error": str(exc),
                    })

    print(f"\nDone. {'Would have processed' if args.dry_run else 'Processed'} "
          f"{len(vaults_data)} vault(s) / {total_items} item(s).")
    print("Category breakdown:")
    for cat, count in sorted(category_counts.items()):
        print(f"  {cat}: {count}")

    if import_log is not None:
        write_import_log(log_path, import_log)
        if import_log["failures"]:
            print(f"  {len(import_log['failures'])} item(s) failed; see log for details.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "xml_file",
        nargs="?",
        help="Path to the Pleasant Password Server XML export (not required with --delete-import if --log-file is set)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without calling the 1Password API")
    parser.add_argument("--list-only", action="store_true", help="Only parse and print the vault/item summary, no SDK calls at all")
    parser.add_argument(
        "--account",
        metavar="NAME",
        help="1Password account name for desktop app auth (overrides OP_ACCOUNT_NAME)",
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        help="Import log path (default: ./<export-basename>.pps-import.json in the current directory)",
    )
    parser.add_argument(
        "--delete-import",
        action="store_true",
        help="Delete vaults and items recorded in a previous import log instead of importing",
    )
    args = parser.parse_args()

    if args.delete_import:
        if args.list_only:
            parser.error("--delete-import cannot be used with --list-only")
        asyncio.run(delete_import(args))
        return

    if not args.xml_file:
        parser.error("xml_file is required unless using --delete-import")
    if args.list_only and args.dry_run:
        parser.error("--list-only cannot be used with --dry-run")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
