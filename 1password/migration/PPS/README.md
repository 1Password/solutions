# Pleasant Password Server → 1Password importer

A single script, `keepass_to_1password.py`, that reads a Pleasant Password
Server XML export and imports it directly into 1Password using the official
[`onepassword-sdk`](https://pypi.org/project/onepassword-sdk/) Python SDK.

Pleasant Password Server exports use the KeePass XML 2.x file format; the
script parses that structure as-is.

## What it does

1. **Parses** the XML export (`<KeePassFile><Root><Group>...`).
2. **One vault per subfolder.** Every folder `Group` that directly contains
   entries becomes one 1Password vault. The vault title is
   `"<folder> - <parent folder>"` — e.g. an export path of
   `.../JAG/Client 1` becomes the vault **"Client 1 - JAG"**. A top-level
   folder with no parent just uses its own name. If two different folders
   would otherwise produce the same title, the script automatically extends
   the title with more of the path until it's unique.
3. **Classifies each entry** into the closest matching 1Password item
   category (Login, Secure Note, Credit Card, Identity, SSH Key, Password,
   Document, API Credentials, Bank Account, Database, Driver License, Email,
   Medical Record, Membership, Outdoor License, Passport, Rewards, Router,
   Server, Social Security Number, Software License) based on the entry's
   field names. See [How classification works](#how-classification-works).
4. **Creates the vaults and items** in 1Password (or reuses a vault that
   already has the same title). Vaults are created up front; items are
   imported in batches of up to 50 per vault via the SDK `create_all` API
   (Document, SSH Key, and Credit Card items are created individually).
5. **Writes an import log** after a real import so you can review what was
   created or roll it back later.

## Setup

```bash
pip install -r requirements.txt
```

Or install the dependency directly:

```bash
pip install onepassword-sdk
```

Authenticate with **either** a service account **or** your signed-in 1Password
desktop app.

### Option A: Service account

Create a 1Password **Service Account** with permission to create vaults and
items:
https://developer.1password.com/docs/service-accounts/get-started

```bash
export OP_SERVICE_ACCOUNT_TOKEN="ops_..."
```

### Option B: Desktop app (no service account)

1. Install the [1Password desktop app](https://1password.com/downloads/).
2. Enable **Settings → Developer → Integrate with other apps**.
3. Set the account name shown in the app sidebar:

```bash
export OP_ACCOUNT_NAME="My Team"
```

Or pass it per run with `--account "My Team"`.

Do not set both `OP_SERVICE_ACCOUNT_TOKEN` and `OP_ACCOUNT_NAME` at the same
time.

## Running on Windows

The script runs on Windows the same way as on macOS or Linux. You need
**Python 3.10+** and the [1Password desktop app](https://1password.com/downloads/)
(if using desktop auth).

1. Install Python from [python.org](https://www.python.org/downloads/windows/)
   (check **Add python.exe to PATH** during setup), or use the **`py`**
   launcher that ships with the Python installer.
2. Open **PowerShell** or **Command Prompt** and go to this folder:

```powershell
cd C:\path\to\PPS
pip install -r requirements.txt
```

If `python` is not recognized, use `py -3` instead (e.g. `py -3 keepass_to_1password.py ...`).

### Environment variables on Windows

**PowerShell (current session):**

```powershell
$env:OP_SERVICE_ACCOUNT_TOKEN = "ops_..."
# or, for desktop app auth:
$env:OP_ACCOUNT_NAME = "My Team"
```

**Command Prompt (current session):**

```cmd
set OP_SERVICE_ACCOUNT_TOKEN=ops_...
set OP_ACCOUNT_NAME=My Team
```

You can also pass desktop account name per run with `--account "My Team"` and
skip setting `OP_ACCOUNT_NAME`.

For desktop auth, install and unlock the 1Password desktop app, then enable
**Settings → Developer → Integrate with other apps** before running the
import.

### Example commands (Windows)

```powershell
# Preview the plan (no auth required)
py -3 keepass_to_1password.py Export.xml --list-only

# Dry run
py -3 keepass_to_1password.py Export.xml --dry-run --account "My Team"

# Import (writes .\Export.pps-import.json in the current directory)
py -3 keepass_to_1password.py C:\Exports\Export.xml --account "My Team"

# Roll back a previous import
py -3 keepass_to_1password.py --delete-import .\Export.pps-import.json --account "My Team"
```

Use forward slashes or quoted paths if filenames contain spaces. The import
log is always written to whatever directory you run the command from (not
next to the XML file).

## Usage

Examples below use `python`; on Windows, use `py -3` if `python` is not on
your PATH (see [Running on Windows](#running-on-windows)).

```bash
# See what would happen — no SDK, no network, no auth required
python keepass_to_1password.py Export.xml --list-only

# Preview the import, including vault existence checks via the SDK
python keepass_to_1password.py Export.xml --dry-run

# Import (writes ./Export.pps-import.json in the current directory by default)
python keepass_to_1password.py Export.xml

# Import with desktop app auth
python keepass_to_1password.py Export.xml --account "My Team"

# Custom import log path
python keepass_to_1password.py Export.xml --log-file /path/to/import-log.json
```

Try it first against the bundled synthetic file, `Sample_Export.xml`, which
exercises every supported item category with fictional data:

```bash
python keepass_to_1password.py Sample_Export.xml --list-only
python keepass_to_1password.py Sample_Export.xml --dry-run
```

### Rolling back an import

After a real import, the script writes a JSON log in the **current working
directory** (default: `./<export-basename>.pps-import.json`) listing every
vault and item it created. Use `--delete-import` to remove that data:

```bash
# Preview what would be deleted
python keepass_to_1password.py Export.xml --delete-import --dry-run

# Delete vaults/items recorded in ./Export.pps-import.json
python keepass_to_1password.py Export.xml --delete-import

# Or point directly at the log file
python keepass_to_1password.py --delete-import Export.pps-import.json
```

Cleanup behavior:

- **Vaults the script created** are deleted entirely (including all items in
  them).
- **Vaults that already existed** are left in place; only the individual
  items added by the import are deleted.
- If cleanup completes successfully, the log file is removed automatically.

The log file contains vault and item IDs — treat it like sensitive data and
do not commit it to source control.

## How classification works

Pleasant Password Server exports have no built-in concept of "item type" —
every entry is just a title/username/password/URL/notes plus whatever custom
fields you or a tool added. There's no universal standard for naming those
custom fields, so this script uses a **best-effort heuristic**: it looks at
the *names* of an entry's custom fields (case- and spacing-insensitive) and
matches them against signatures for each 1Password category. For example, an
entry with `Card Number` and `CVV` fields is classified as a Credit Card; an
entry with only `Notes` and nothing else becomes a Secure Note; an entry
with `SSH Private Key` becomes an SSH Key item.

**This is not guaranteed to be perfect.** If your export entries use
different field-naming conventions than the ones listed below, entries will
fall back to Login (if they have a username/password), Password (password
only, no username), or Secure Note (notes only). You can always review and
recategorize items afterward in 1Password — nothing is deleted from the
source, and no field data is discarded (see [What happens to
data that doesn't fit a known field](#what-happens-to-data-that-doesnt-fit-a-known-field)
below).

### Recognized field-name signatures

| 1Password category | Trigger field names (normalized) |
|---|---|
| SSH Key | `SSH Private Key` |
| Crypto Wallet | `Wallet Address`, `Recovery Phrase`, `Seed Phrase`, `Private Key (WIF)`, `Cryptocurrency` |
| Credit Card | `Card Number`, `CVV`, `Cardholder Name`, `Card Type` |
| Bank Account | `Account Number`, `Routing Number`, `IBAN`, `Bank Name` |
| Social Security Number | `SSN`, `Social Security Number` |
| Passport | `Passport Number`, `Nationality` |
| Driver License | `License Number`, `License State`, `License Class` |
| Software License | `License Key`, `Serial Number`, `Licensed To` |
| Outdoor License | `Permit Number`, `Hunting Season`, `Game Zone` |
| Medical Record | `Blood Type`, `Policy Number`, `Physician Name`, `Medical Conditions` |
| Membership | `Membership Number`, `Membership Level` |
| Rewards | `Rewards Number`, `Points Balance`, `Tier Status` |
| API Credentials | `API Key`, `Client ID`, `Client Secret`, `Access Token` |
| Database | any two of `Database Name`, `Hostname`, `Port` |
| Server | `IP Address`, `OS Version`, `Server Name` |
| Router | `SSID`, `WiFi Password`, `Router Admin URL` |
| Identity | any two of `First Name`, `Last Name`, `Date of Birth`, `Address`, `City` |
| Email | `IMAP Server`, `POP3 Server`, `SMTP Server`, `Email Address` |
| Secure Note (contact) | `Full Name` or `Relationship` — see note below |
| Document | entry has a file attachment in the export |
| Secure Note | only `Notes` is populated (no username/password/URL) |
| Password | `Password` populated, no `UserName` |
| Login | default fallback |

**Contact entries:** Export entries with `Full Name` / `Relationship` fields
are classified as contact-style data, but the SDK cannot create native
**Person** items. They are imported as **Secure Notes** with the contact
fields preserved in a Details section.

A one-time password (`otp`/`TOTP` field, including an `otpauth://` URI) is
detected on any entry and added as a proper TOTP field regardless of
category.

### Import fallbacks

If a specific item type cannot be created, the script retries as a Secure
Note rather than stopping the whole import:

- **SSH Key** — unparseable or placeholder key material
- **Document** — attachment could not be attached as a native Document item
- **Other structured categories** — SDK rejects the item payload

Failed items are also recorded in the import log under `failures`.

### What happens to data that doesn't fit a known field

- Recognized fields (the table above) are mapped to an appropriately-typed
  1Password field (e.g. card number → Credit Card Number field, expiry date
  → Month/Year field, SSN/CVV/API keys → Concealed field) inside a
  **"Details"** section.
- Any other custom field from the export is preserved as a Text or Concealed
  field (guessed from the field name — anything containing "password",
  "secret", "key", "pin", "cvv", "ssn", "private", or "token" is treated as
  a secret) inside an **"Export metadata"** section, so nothing is silently
  dropped.
- `Notes` always carries over as the item's Notes field.

## Flags

| Flag | Effect |
|---|---|
| `--list-only` | Parse and print the vault/item/category plan. No SDK, no network, no auth required. |
| `--dry-run` | Preview actions via the SDK (vault checks on import; deletion preview on cleanup). Creates nothing. Requires the SDK and valid auth. |
| `--account NAME` | 1Password account name for desktop app auth (overrides `OP_ACCOUNT_NAME`). |
| `--log-file PATH` | Import log path (default: `./<export-basename>.pps-import.json` in the current directory). |
| `--delete-import` | Delete vaults/items from a previous import log instead of importing. Use with `--dry-run` to preview. |
| (no flag) | Run the import and write the log file. |

`--list-only` and `--dry-run` cannot be combined. `--delete-import` cannot
be used with `--list-only`.

## Import log format

The log is JSON with this structure:

```json
{
  "source_xml": "/path/to/Export.xml",
  "imported_at": "2026-01-15T12:00:00+00:00",
  "vaults": [
    {
      "title": "Client 1 - JAG",
      "id": "vault-id",
      "created": true,
      "items": [
        {
          "title": "Example Login",
          "id": "item-id",
          "category": "Login",
          "planned_category": "Login"
        }
      ]
    }
  ],
  "failures": []
}
```

- `created: true` — the script created this vault; `--delete-import` removes
  the whole vault.
- `created: false` — the script reused an existing vault; `--delete-import`
  removes only the listed items.

## Notes and limitations

- **Vault titles must be unique in a 1Password account.** If a vault with
  the computed title already exists, the script reuses it instead of
  creating a duplicate.
- **Attachments:** only the first file attached to an export entry is
  imported, as the item's single Document file, and only for entries
  classified as Document. Attachments on entries of other categories aren't
  currently uploaded as field-level files.
- **Address fields** are stored as plain text (street/city/etc. as separate
  text fields) rather than 1Password's structured Address field type, to
  keep the mapping simple and predictable.
- Export `TOTPDigits`/`TOTPPeriod`/etc. settings (as opposed to an actual
  seed) carry over into the Export metadata section if present, since
  1Password derives digit/period info from the TOTP seed or `otpauth://` URI
  itself.
- **Re-running an import** against the same export will reuse existing vaults
  by title and may create duplicate items. Use the import log and
  `--delete-import` to clean up test runs.
- **Batch import:** most items are created with `items.create_all()` in chunks
  of 50. Document, SSH Key, and Credit Card items are always created one at
  a time because they carry binary data or need special SDK handling. If a
  batch call fails for a single item, the script retries that item
  individually (including Secure Note fallbacks).

## Files in this folder

- `keepass_to_1password.py` — the importer (parsing, classification,
  1Password import, logging, and cleanup).
- `requirements.txt` — Python dependencies (`onepassword-sdk`).
- `Sample_Export.xml` — a synthetic Pleasant Password Server export with
  entirely fictional data (fake names, `example.com` addresses, RFC 5737 test
  IP ranges, the well-known `4111111111111111` test Visa number, etc.)
  covering every supported item category, for trying the script out safely.

## Security note

A real Pleasant Password Server export contains live plaintext passwords
once decrypted to XML. Treat the export file, import logs, and anything
derived from them as secrets: avoid committing them to source control,
delete them once the import is complete, and don't leave copies lying around
in shared folders.
