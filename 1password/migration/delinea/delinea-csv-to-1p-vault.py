#!/usr/bin/env python3
"""
delinea_to_1password.py

Reads a Delinea (Secret Server) CSV export and creates a new 1Password vault
named "Delinea Export - YYYY-MM-DD", then bulk-creates one item per secret
using the 1Password Python SDK's batch item-creation API.

Delinea's multi-template export format
---------------------------------------
When Secret Server exports secrets that use different templates (AD Account,
Azure Account, Cisco Account, Eltek Password, OpenLDAP Account, etc.), it
does NOT produce one CSV with a single fixed header. Instead every secret is
written as its own two-line block: a header row (always starting with
"Secret Name") describing that secret's columns, immediately followed by one
data row using those columns. The next secret's header can have entirely
different columns. For example:

    Secret Name,Domain,Username,Password,Notes,Location,Server List,URL,Folder,TOTP Key,TOTP Backup Codes
    AD Account Example,corp.local,jane.doe,hunter2,,,,,\\Folder\\Path,,
    Secret Name,Host,Username,Password,Notes,Priviledge Level,DeviceModel,Folder,TOTP Key,TOTP Backup Codes,
    Cisco Account Example,switch01,admin,hunter3,,,,\\Folder\\Path,,

This script parses that shape directly (a plain `csv.DictReader` over the
whole file would misread it, since headers repeat and change mid-file), then
maps each row's own columns onto 1Password fields.

Authentication
--------------
This script authenticates to 1Password with a SERVICE ACCOUNT TOKEN, read
from the OP_SERVICE_ACCOUNT_TOKEN environment variable (never hardcode it,
and never commit it to source control).

    export OP_SERVICE_ACCOUNT_TOKEN="ops_..."

The service account MUST have the "Create Vaults" permission turned on, in
addition to Read/Write on any vault it needs to write items into. Service
accounts cannot update or delete vaults they didn't create, and 1Password
recommends using the desktop app (not a service account) for general vault
management -- but a service account is the right tool for a headless/CI
import like this one, as long as the permission is granted.
See: https://developer.1password.com/docs/service-accounts/get-started

Note on "the token that authenticates to the token store": the service
account token is the bootstrap credential for talking to 1Password itself,
so it cannot be replaced with an op:// secret reference (nothing has
resolved it yet). Keep it in your OS keychain, your CI secret store, or a
password manager other than plaintext files/shell history. Every OTHER
secret this script touches ends up inside 1Password, which is the point of
running it.

Install
-------
    pip install onepassword-sdk

Usage
-----
    export OP_SERVICE_ACCOUNT_TOKEN="ops_..."
    python delinea_to_1password.py --csv secrets-export.csv

    # Preview the mapping without creating anything in 1Password:
    python delinea_to_1password.py --csv secrets-export.csv --dry-run

    # Override the vault name or item category:
    python delinea_to_1password.py --csv secrets-export.csv \\
        --vault-title "Delinea Export - 2026-08-05 (Prod Servers)" \\
        --category LOGIN
"""

import argparse
import asyncio
import csv
import os
import sys
from datetime import date
from itertools import zip_longest
from typing import Dict, List, Optional, Tuple

try:
    from onepassword import (
        Client,
        ItemCategory,
        ItemCreateParams,
        ItemField,
        ItemFieldType,
        ItemSection,
        VaultCreateParams,
    )
except ImportError:
    # Allow --dry-run (mapping preview only) to work without the SDK
    # installed. Any real run still requires `pip install onepassword-sdk`.
    Client = ItemCreateParams = ItemField = ItemSection = VaultCreateParams = None

    class _StubEnum:
        """Fallback so --category validation doesn't crash without the SDK."""

        def __getitem__(self, key):
            return key

    ItemCategory = _StubEnum()
    ItemFieldType = _StubEnum()

BATCH_SIZE = 100  # SDK limit for items.create_all()

# Candidate CSV column names (case-insensitive) mapped to a canonical field.
# Delinea/Secret Server exports vary by template, so we match generously.
# A given row will only ever populate the canonical fields whose alias
# actually appears in *that row's* header -- unmatched columns fall through
# to a generic "Delinea Details" section so nothing is silently dropped.
COLUMN_ALIASES: Dict[str, List[str]] = {
    "title": ["secret name", "secretname", "name", "title"],
    "domain": ["domain"],
    "server": [
        "machine",
        "server",
        "server address",
        "host",
        "hostname",
        "ip address",
        "resource name",
    ],
    "username": ["username", "user name", "user", "account", "login"],
    "password": ["password", "secret", "passwd"],
    "url": ["url", "website", "site", "connection string"],
    "notes": ["notes", "comment", "comments", "description"],
    "folder": ["folder path", "folderpath", "folder"],
    "template": ["secret template", "secret template name", "template", "type"],
    "totp": ["totp key", "totp secret", "one time password", "otp"],
}

DELINEA_DETAILS_SECTION_ID = "delineaDetails"
HEADER_MARKER = "secret name"


def parse_delinea_csv(path: str) -> List[Tuple[Tuple[str, ...], Dict[str, str]]]:
    """
    Parse Delinea's multi-header export format.

    Every secret is a (header row, data row) pair; the header row always
    starts with "Secret Name" and its columns can differ from the previous
    secret's. Returns a list of (header_tuple, row_dict) so callers can
    still group/report by which column set ("template shape") each row used.
    """
    entries: List[Tuple[Tuple[str, ...], Dict[str, str]]] = []
    current_header: Optional[List[str]] = None

    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw_row in csv.reader(f):
            if not raw_row or all(not cell.strip() for cell in raw_row):
                continue  # skip blank lines
            if raw_row[0].strip().lower() == HEADER_MARKER:
                current_header = [cell.strip() for cell in raw_row]
                continue
            if current_header is None:
                print(
                    f"Warning: skipping row before any header was seen: {raw_row}",
                    file=sys.stderr,
                )
                continue
            row_dict: Dict[str, str] = {}
            for col_name, value in zip_longest(current_header, raw_row, fillvalue=""):
                col_name = (col_name or "").strip()
                if not col_name:
                    continue  # trailing empty column from a trailing comma
                row_dict[col_name] = (value or "").strip()
            entries.append((tuple(current_header), row_dict))

    return entries


def build_column_map(fieldnames: List[str]) -> Dict[str, str]:
    """Map canonical field -> actual CSV column name found in this header."""
    lower_to_actual = {fn.strip().lower(): fn for fn in fieldnames if fn.strip()}
    mapping: Dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_to_actual:
                mapping[canonical] = lower_to_actual[alias]
                break
    return mapping


def row_to_item_params(
    row: Dict[str, str],
    vault_id: str,
    column_map: Dict[str, str],
    category,
    row_index: int,
) -> "ItemCreateParams":
    """Turn one parsed secret (row_dict + its own column_map) into an ItemCreateParams."""

    def get(canonical: str) -> Optional[str]:
        col = column_map.get(canonical)
        if not col:
            return None
        value = row.get(col)
        return value if value else None

    title = get("title") or f"Delinea Import Row {row_index}"
    domain = get("domain")
    server = get("server")
    username = get("username")
    password = get("password")
    url = get("url")
    notes = get("notes")
    folder = get("folder")
    template = get("template")
    totp = get("totp")

    fields: List["ItemField"] = []
    sections: List["ItemSection"] = [ItemSection(id="", title="")]

    if username is not None:
        fields.append(
            ItemField(
                id="username",
                title="username",
                field_type=ItemFieldType.TEXT,
                value=username,
            )
        )
    if password is not None:
        fields.append(
            ItemField(
                id="password",
                title="password",
                field_type=ItemFieldType.CONCEALED,
                value=password,
            )
        )
    if domain is not None:
        fields.append(
            ItemField(
                id="domain",
                title="domain",
                field_type=ItemFieldType.TEXT,
                value=domain,
            )
        )
    if totp is not None:
        # Delinea's "TOTP Key" is a raw base32 seed, which the 1Password SDK
        # accepts directly for a Totp field (an otpauth:// URI also works).
        fields.append(
            ItemField(
                id="totp",
                title="one-time password",
                field_type=ItemFieldType.TOTP,
                value=totp,
            )
        )
    if server is not None:
        # Stored as a labeled text field since "Server"/"Host" isn't a
        # universal built-in field id across every item category.
        fields.append(
            ItemField(
                id="server",
                title="server",
                field_type=ItemFieldType.TEXT,
                value=server,
                section_id=DELINEA_DETAILS_SECTION_ID,
            )
        )

    # Everything else that didn't map to a known canonical field goes into a
    # "Delinea Details" section as plain text fields, so no column from the
    # export is ever silently dropped -- even oddball per-template columns
    # like "Priviledge Level", "DeviceModel", "Site ID", or "TOTP Backup Codes".
    mapped_columns = {column_map[c] for c in column_map if c not in ("template",)}
    for csv_column, value in row.items():
        if csv_column in mapped_columns or not value:
            continue
        safe_id = "".join(c if c.isalnum() else "_" for c in csv_column.lower())
        fields.append(
            ItemField(
                id=f"delinea_{safe_id}",
                title=csv_column,
                field_type=ItemFieldType.TEXT,
                value=value,
                section_id=DELINEA_DETAILS_SECTION_ID,
            )
        )

    if any(
        getattr(f, "section_id", None) == DELINEA_DETAILS_SECTION_ID for f in fields
    ):
        sections.append(
            ItemSection(id=DELINEA_DETAILS_SECTION_ID, title="Delinea Details")
        )

    websites = []
    if url:
        websites.append(
            {"url": url, "label": "url", "autofillBehavior": "AnywhereOnWebsite"}
        )

    tags = ["delinea-import"]
    if folder:
        tags.append(folder)
    if template:
        tags.append(f"template:{template}")

    return ItemCreateParams(
        title=title,
        category=category,
        vault_id=vault_id,
        fields=fields,
        sections=sections,
        notes=notes or "",
        tags=tags,
    )


def chunked(items: List, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a Delinea Secret Server CSV export into a new 1Password vault."
    )
    parser.add_argument("--csv", required=True, help="Path to the Delinea CSV export.")
    parser.add_argument(
        "--vault-title",
        default=None,
        help='Vault title. Defaults to "Delinea Export - YYYY-MM-DD".',
    )
    parser.add_argument(
        "--vault-description",
        default="Imported from a Delinea Secret Server CSV export.",
        help="Description to set on the newly created vault.",
    )
    parser.add_argument(
        "--category",
        default="LOGIN",
        help="1Password item category to create rows as (default: LOGIN). "
        "See ItemCategory in the SDK for valid values (LOGIN, SERVER, PASSWORD, etc).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print the mapping/item count without contacting 1Password.",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"CSV file not found: {args.csv}", file=sys.stderr)
        return 1

    try:
        category = ItemCategory[args.category.upper()]
    except KeyError:
        print(f"Unknown item category: {args.category}", file=sys.stderr)
        return 1

    vault_title = args.vault_title or f"Delinea Export - {date.today().isoformat()}"

    entries = parse_delinea_csv(args.csv)
    if not entries:
        print(
            "No secrets found in CSV (no header/data pairs detected).", file=sys.stderr
        )
        return 1

    print(f"Loaded {len(entries)} secret(s) from {args.csv}")

    # Group by header shape purely for a readable preview -- actual mapping
    # happens per-row below, so mixed templates in one file are fine.
    by_header: Dict[Tuple[str, ...], List[Dict[str, str]]] = {}
    for header, row in entries:
        by_header.setdefault(header, []).append(row)

    print(f"Detected {len(by_header)} distinct column layout(s) (template shapes):")
    for header, rows in by_header.items():
        column_map = build_column_map(list(header))
        example_title = rows[0].get(column_map.get("title", ""), "?")
        unmapped = [c for c in header if c and c not in column_map.values()]
        print(f'\n  Layout with {len(rows)} secret(s), e.g. "{example_title}":')
        print(f"    columns: {list(header)}")
        for canonical, actual in column_map.items():
            print(f"      {canonical:10s} <- '{actual}'")
        if unmapped:
            print(f"      (unmapped -> custom fields: {unmapped})")

    if args.dry_run:
        print(
            f"\n[dry run] Would create vault '{vault_title}' and {len(entries)} item(s). Stopping here."
        )
        return 0

    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
    if not token:
        print(
            "OP_SERVICE_ACCOUNT_TOKEN is not set. Export your 1Password service "
            "account token into that environment variable before running this script.",
            file=sys.stderr,
        )
        return 1

    client = await Client.authenticate(
        auth=token,
        integration_name="Delinea CSV Import",
        integration_version="v1.0.0",
    )

    print(f"\nCreating vault '{vault_title}'...")
    try:
        vault = await client.vaults.create(
            VaultCreateParams(title=vault_title, description=args.vault_description)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to create vault: {exc}", file=sys.stderr)
        print(
            "Make sure the service account has the 'Create Vaults' permission. "
            "See https://developer.1password.com/docs/service-accounts/get-started",
            file=sys.stderr,
        )
        return 1
    print(f"Created vault '{vault.title}' ({vault.id})")

    items_to_create = []
    for i, (header, row) in enumerate(entries, start=1):
        column_map = build_column_map(list(header))
        items_to_create.append(
            row_to_item_params(row, vault.id, column_map, category, i)
        )

    created_count = 0
    failed_count = 0

    for batch_num, batch in enumerate(chunked(items_to_create, BATCH_SIZE), start=1):
        print(f"\nCreating batch {batch_num} ({len(batch)} item(s))...")
        try:
            response = await client.items.create_all(vault.id, batch)
        except Exception as exc:  # noqa: BLE001
            print(f"Batch {batch_num} failed entirely: {exc}", file=sys.stderr)
            failed_count += len(batch)
            continue

        for res in response.individual_responses:
            if res.content is not None:
                created_count += 1
                print(f'  Created "{res.content.title}" ({res.content.id})')
            elif res.error is not None:
                failed_count += 1
                print(f"  FAILED: {res.error}", file=sys.stderr)

    print(f"\nDone. {created_count} item(s) created, {failed_count} failed.")
    print(f"Vault: '{vault.title}' ({vault.id})")
    return 0 if failed_count == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
