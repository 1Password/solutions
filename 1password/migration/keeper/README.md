# Keeper → 1Password Migration

Migrate Keeper exports into 1Password using `import-from-keeper.py`. The script supports both **JSON-only** and **ZIP (with attachments)** input, creates vaults, maps shared-folder permissions to vault access (groups via SDK, users via CLI), and bulk-creates items.

---

## Requirements

- **Python 3.8+**
- **1Password CLI v2** (`op`) — for vault creation and user permission grants
- **Auth**: `OP_SERVICE_ACCOUNT_TOKEN` (service account needs create-vault and appropriate access)
- **Keeper export**: [CLI export](https://docs.keeper.io/en/keeperpam/commander-cli/command-reference/import-and-export-commands#export-command) or [UI vault export](https://docs.keeper.io/en/user-guides/export-and-reports/vault-export)
- **Permission mapping**: Users and groups must already exist in 1Password with the same names/emails as in Keeper.

**Install:** `pip install -r requirements.txt` (uses `onepassword-sdk` beta).

---

## Input formats

- **JSON** — Single file with `shared_folders` and `records`. Data only; no attachments.
- **ZIP** — Archive containing:
  - `export.json` — same structure as above
  - `files/` — attachment blobs named by UID (from Keeper export with files)

The script uses the file extension to decide: **.zip** = import with attachments, **.json** = data only.

---

## Usage

```bash
# With attachments (ZIP)
python import-from-keeper.py --input export-files.zip --employee-vault "Keeper Import"

# Data only (JSON)
python import-from-keeper.py --input export.json --employee-vault "Keeper Import"

# Grant a user access to private vaults (e.g. service account runner)
python import-from-keeper.py --input export-files.zip --employee-vault "Keeper Import" --user-for-private you@example.com

# Preview without creating or granting
python import-from-keeper.py --input export-files.zip --employee-vault "Keeper Import" --dry-run
```

| Argument | Description |
|----------|-------------|
| `--input` | Path to `.zip` (export with files) or `.json` (data only) |
| `--employee-vault` | Vault for records with no folder |
| `--private-prefix` | Prefix for private vault names (default: `Private - `) |
| `--user-for-private` | User (e.g. email) to grant access to private vaults (allow_editing + allow_viewing) |
| `--dry-run` | Show planned actions only |
| `--silent` | Suppress progress output |

---

## Example JSON structure

```json
{
  "shared_folders": [
    {
      "path": "Engineering\\DevOps",
      "manage_users": true,
      "manage_records": true,
      "permissions": [
        { "name": "devops-team", "manage_users": true, "manage_records": true },
        { "name": "alice@example.com", "manage_users": false, "manage_records": true }
      ]
    }
  ],
  "records": [
    {
      "title": "GitHub Production",
      "login": "deploy-bot",
      "password": "SuperSecret123!",
      "login_url": "https://github.com",
      "notes": "Used for CI/CD automation.",
      "custom_fields": { "TOTP": "otpauth://totp/..." },
      "folders": [ { "shared_folder": "Engineering\\DevOps" } ],
      "$type": "login"
    }
  ]
}
```

---

## Limitations

- **Per-item permissions** (e.g. Keeper’s `can_edit` / `can_share`) are not supported; 1Password uses vault-level permissions only.
- Records in **multiple folders** are **duplicated** into each corresponding vault.
- Users/groups must exist in 1Password with matching names/emails; unknown subjects are skipped with a warning.
