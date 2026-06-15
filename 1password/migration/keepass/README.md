# KeePass XML → 1Password Importer

Migrates a KeePass XML 2.x export into 1Password using the [onepassword-sdk](https://github.com/1Password/onepassword-sdk-python) bulk-create API.

## Features

- **Password history** — each entry's historical passwords are appended to the item's Notes field (newest first, duplicates suppressed)
- **Attachments** — binary attachments from the KeePass pool are imported as 1Password file attachments
- **TOTP** — `otpauth://` URIs are mapped to a proper OTP field
- **Group → Vault mapping** — KeePass groups become 1Password vaults; sub-groups either get their own vault or collapse into the parent as tags (see `--collapse-folders`)
- **Recycle Bin** — skipped automatically
- **Resumable** — a state file is written on interruption (e.g. rate limit); re-running the same command picks up where it left off

## Requirements

| Requirement                | Notes                                                        |
| -------------------------- | ------------------------------------------------------------ |
| Python 3.9+                |                                                              |
| `OP_SERVICE_ACCOUNT_TOKEN` | Set as an environment variable                               |
| `onepassword-sdk`          | Auto-installed into `.venv-1pw` if missing                   |
| `op` CLI                   | Only needed for `--user-for-private` vault permission grants |

## Usage

```bash
export OP_SERVICE_ACCOUNT_TOKEN=your-token-here

# Preview — no changes made
python import-from-keepass-xml.py \
  --input keepass-export.xml \
  --employee-vault "KeePass Import" \
  --dry-run

# Live import
python import-from-keepass-xml.py \
  --input keepass-export.xml \
  --employee-vault "KeePass Import"

# Collapse sub-groups into parent vaults (sub-groups become tags)
python import-from-keepass-xml.py \
  --input keepass-export.xml \
  --employee-vault "KeePass Import" \
  --collapse-folders

# Grant a user edit access to all imported vaults
python import-from-keepass-xml.py \
  --input keepass-export.xml \
  --employee-vault "KeePass Import" \
  --user-for-private user@example.com
```

## Options

| Flag                 | Default      | Description                                                   |
| -------------------- | ------------ | ------------------------------------------------------------- |
| `--input`            | _(required)_ | Path to KeePass XML 2.x export                                |
| `--employee-vault`   | _(required)_ | Fallback vault for entries with no group                      |
| `--private-prefix`   | `""`         | String prepended to vault names derived from groups           |
| `--collapse-folders` | off          | Collapse sub-groups into parent vault; sub-groups become tags |
| `--user-for-private` | —            | Grant this user (email) edit access to all vaults             |
| `--dry-run`          | off          | Print planned actions without creating anything               |
| `--silent`           | off          | Suppress progress output                                      |

## Vault mapping

Without `--collapse-folders`, each unique group path becomes its own vault:

```
Email          → vault "Email"
Email/Work     → vault "Email/Work"
Development    → vault "Development"
Development/Cloud → vault "Development/Cloud"
```

With `--collapse-folders`, only the top-level group is a vault; deeper paths become tags:

```
Email          → vault "Email",  tag "Email"
Email/Work     → vault "Email",  tag "Email\Work"
Development/Cloud → vault "Development", tag "Development\Cloud"
```

Entries with no group go to the `--employee-vault`.

## Password history format

Historical passwords are appended to the item's Notes field:

```
--- Password History ---
2024-01-15T09:23:00Z  previous-password
2022-06-01T14:00:00Z  older-password
```

The current password is never repeated in the history block. Exact duplicate historical passwords are suppressed.

## Resuming an interrupted import

If the import is interrupted, a `.import-state.json` file is written next to the input file. Re-run the exact same command to resume — completed items are skipped. The state file is deleted automatically on full success.

## Testing

A test XML file (`keepass-test-export.xml`) is provided. It covers logins, secure notes, TOTP, attachments, nested groups, password history with duplicates, and a Recycle Bin entry that should be skipped.

```bash
python import-from-keepass-xml.py \
  --input keepass-test-export.xml \
  --employee-vault "KeePass Import" \
  --dry-run
```
