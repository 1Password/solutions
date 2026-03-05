# Keeper → 1Password Migration

Migrate Keeper exports into 1Password using `import-from-keeper.py`. The script supports **JSON**, **ZIP (with attachments)**, and **KDBX** input, creates vaults automatically via the SDK, maps shared-folder permissions to vault access (groups via SDK, users printed as CLI commands), and bulk-creates items in batches of 100.

Dependencies are installed automatically into a local `.venv-1pw` virtual environment on first run — no manual `pip install` needed.

---

## Requirements

- **Python 3.8+**
- **Auth**: `OP_SERVICE_ACCOUNT_TOKEN` (service account needs create-vault and appropriate item access)
- **Keeper export**: [CLI export](https://docs.keeper.io/en/keeperpam/commander-cli/command-reference/import-and-export-commands#export-command) or [UI vault export](https://docs.keeper.io/en/user-guides/export-and-reports/vault-export)
- **Permission mapping**: Users and groups must already exist in 1Password with the same names/emails as in Keeper.

**Packages** (`requirements.txt`): `onepassword-sdk` (beta) and `pykeepass` (for KDBX input). The script installs these automatically on first run — or installs from `requirements.txt` if one exists next to the script.

---

## Keeper export formats

### ZIP (credentials + attachments)
```bash
# Export vault to a ZIP containing export.json and files/ (attachments)
keeper export export-files.zip --format json --zip

# Optional: cap attachment size (e.g. skip very large files)
keeper export export-files.zip --format json --zip --max-size 50M
```

### JSON (credentials + folder structure, no attachments)
```bash
keeper export export.json --format json
```

### KDBX (credentials + attachments, no shared folder permissions)

Export from the Keeper desktop app or web vault: **Settings → Export → KeePass Format (.kdbx)**. You will be prompted to set a password — this is the password the script will ask for at runtime.

> **Note:** KDBX does not include shared folder permission data. For a full migration (permissions + attachments), run JSON first to establish vaults and permissions, then KDBX to add attachments. The script's resumability prevents duplicates.

---

## Input formats

| Format | Credentials | Folder structure | Permissions | Attachments |
|--------|-------------|-----------------|-------------|-------------|
| `.json` | ✅ | ✅ | ✅ | ❌ |
| `.zip` | ✅ | ✅ | ✅ | ✅ |
| `.kdbx` | ✅ | ✅ (from group hierarchy) | ❌ | ✅ (≤1MB each) |

The script detects format from the file extension automatically.

---

## Folder → Vault mapping

Without `--collapse-folders` (default):
- Top-level folder items → vault named after the folder, tagged with the folder name
- Sub-folder items → vault named after the **child folder only**, tagged with `Parent\Child`

With `--collapse-folders`:
- All items go into the **parent vault**
- Top-level items tagged with parent name
- Sub-folder items tagged with `Parent\Child`

---

## Resumability

If the import is interrupted (e.g. by a rate limit), a state file is written next to the input file. Re-running the same command resumes from where it left off — completed items are skipped. The state file is deleted automatically on full success.

---

## Usage

```bash
# JSON (credentials + folder structure, no attachments)
python import-from-keeper.py --input export.json --employee-vault "Keeper Import"

# ZIP (credentials + folder structure + attachments)
python import-from-keeper.py --input export-files.zip --employee-vault "Keeper Import"

# KDBX (credentials + attachments, prompts for KeePass password)
python import-from-keeper.py --input export.kdbx --employee-vault "Keeper Import"

# Collapse sub-folders into parent vault, using tags for sub-folder paths
python import-from-keeper.py --input export.json --employee-vault "Keeper Import" --collapse-folders

# Grant a user access to private vaults
python import-from-keeper.py --input export.json --employee-vault "Keeper Import" --user-for-private you@example.com

# Preview without creating anything
python import-from-keeper.py --input export.json --employee-vault "Keeper Import" --dry-run
```

| Argument | Description |
|----------|-------------|
| `--input` | Path to `.zip`, `.json`, or `.kdbx` export file |
| `--employee-vault` | Fallback vault for records with no folder assignment |
| `--private-prefix` | Prefix for private vault names (default: `Private - `) |
| `--collapse-folders` | Collapse sub-folders into parent vault; use tags for sub-folder paths |
| `--user-for-private` | User email to grant access to private vaults (`allow_editing` + `allow_viewing`) |
| `--dry-run` | Show planned actions only — nothing is created |
| `--silent` | Suppress progress output |

---

## Permissions

Group permissions are granted automatically via the SDK. User-level vault grants are not yet supported by the SDK — the script will print the equivalent CLI commands at the end of the run for you to apply manually:

```
⚠  2 user-level vault grant(s) require manual action:
   op vault user grant --vault 'Engineering' --user 'alice@example.com' --permissions allow_viewing,allow_editing
   op vault user grant --vault 'Engineering' --user 'bob@example.com' --permissions allow_viewing
```

Permission mapping from Keeper:

| Keeper | 1Password |
|--------|-----------|
| `manage_users: true` | `allow_managing` |
| `manage_records: true` | `allow_editing` |
| default | `allow_viewing` |

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
      "folders": [ { "shared_folder": "Engineering\\DevOps", "folder": "DevOps" } ],
      "$type": "login"
    }
  ]
}
```

---

## Limitations

- **Per-item permissions** (e.g. Keeper's `can_edit` / `can_share`) are not supported; 1Password uses vault-level permissions only.
- Records in **multiple folders** are duplicated into each corresponding vault.
- Users/groups must exist in 1Password with matching names/emails; unknown subjects are skipped with a warning.
- **KDBX attachments** are capped at 1MB by the KeePass format. Use ZIP export for larger attachments.
- **User vault grants** must be applied manually via the CLI after import (SDK limitation).