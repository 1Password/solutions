# Keeper → 1Password Migration Tool

This repository provides a Python script (`migrate_from_json.py`) that migrates data from a Keeper JSON export into [1Password](https://developer.1password.com/docs/cli) using the 1Password CLI (`op`).

## Features

- **Vault creation**:
  - Creates vaults for each Keeper **shared folder**, mapping permissions (users and groups).
  - Creates **private vaults** for non-shared folders (prefix defaults to `Private - `).
  - Ensures the specified **employee vault** exists.
- **Permission mapping**:
  - Approximates Keeper permissions to 1Password vault permissions:
    - `manage_users` → `allow_managing`
    - `manage_records` → `allow_editing`
    - Always includes `allow_viewing`.
- **Item migration**:
  - Migrates Keeper records as 1Password items.
  - Creates **Login items** (with username, password, URL, notes, and TOTP).
  - Creates **Secure Notes** for records without login credentials.
  - Places items into the correct vault(s). Items with no folder go into the employee vault.
- **Dry-run support** to preview actions without making changes.

## Requirements

- Python 3.8+
- 1Password CLI v2 (`op`)
- An active 1Password CLI session:
  - Either signed in interactively (`op signin`)
  - Or using a service account with `OP_SERVICE_ACCOUNT_TOKEN` - the service account needs "Create Vault" permissions
- A json export from keeper [Through the CLI](https://docs.keeper.io/en/keeperpam/commander-cli/command-reference/import-and-export-commands#export-command) or [the UI](https://docs.keeper.io/en/user-guides/export-and-reports/vault-export)
- The groups and users already created with the same names and emails as in Keeper

## Example Input

Example `keeper.json` file:

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
      "custom_fields": { "TOTP": "otpauth://totp/GitHub:deploy-bot?secret=JBSWY3DPEHPK3PXP&issuer=GitHub" },
      "folders": [ { "shared_folder": "Engineering\\DevOps" } ],
      "$type": "login"
    }
  ]
}
```

## Usage

```bash
# Preview migration without making changes
python migrate_from_json.py \\
  --input keeper.json \\
  --employee-vault "Keeper Import" \\
  --dry-run --silent

# Perform migration (real run)
python migrate_from_json.py \\
  --input keeper.json \\
  --employee-vault "Keeper Import" \\
  --user-for-private you@example.com \\
  --silent
```

### Arguments

- `--input`: Path to the Keeper JSON export.
- `--employee-vault`: Name of the vault for records without a folder.
- `--private-prefix`: Prefix for non-shared folder vaults (default: `Private - `).
- `--user-for-private`: Email of the user who should get access to private vaults. This is especially important for if using a service account to run the script.
- `--dry-run`: Print planned actions without calling `op`.
- `--silent`: Don't print progress messages.

## Limitations

- **Per-item permissions** (`can_edit`, `can_share`) are ignored. 1Password only supports vault-level permissions.
- If a record is in multiple folders, it is **duplicated** across vaults.
- Subjects (users/groups) must exist in 1Password. If not found, the script will warn and skip those grants.
- Vaults marked "Private" will still be accessible to owners and administrators
