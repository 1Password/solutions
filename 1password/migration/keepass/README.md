# KeePass XML → 1Password Importer

Migrates a KeePass XML 2.x export into a single 1Password vault using the [onepassword-sdk](https://github.com/1Password/onepassword-sdk-python) bulk-create API. The vault is created by the service account if it does not already exist.

## Features

- **Single vault** — all entries land in one vault; the service account creates it if needed
- **Group → tag mapping** — KeePass group paths become tags, with one tag per level of hierarchy
- **Password history** — KeePass history is replayed as real 1Password item history (viewable via "View password history" in the UI)
- **Attachments** — binary attachments are imported as 1Password file attachments
- **TOTP** — `otpauth://` URIs are mapped to a proper OTP field
- **Recycle Bin** — skipped automatically
- **Resumable** — a state file is written on interruption (e.g. rate limit); re-running the same command picks up where it left off

## Requirements

| Requirement                | Notes                                      |
| -------------------------- | ------------------------------------------ |
| Python 3.9+                |                                            |
| `OP_SERVICE_ACCOUNT_TOKEN` | Set as an environment variable             |
| `onepassword-sdk`          | Auto-installed into `.venv-1pw` if missing |

## Usage

```bash
export OP_SERVICE_ACCOUNT_TOKEN=your-token-here

# Preview — no changes made
python import-from-keepass-xml.py \
  --input keepass-export.xml \
  --vault "KeePass Import" \
  --dry-run

# Live import
python import-from-keepass-xml.py \
  --input keepass-export.xml \
  --vault "KeePass Import"
```

## Options

| Flag        | Description                                                      |
| ----------- | ---------------------------------------------------------------- |
| `--input`   | Path to KeePass XML 2.x export _(required)_                      |
| `--vault`   | Destination vault name; created if it doesn't exist _(required)_ |
| `--dry-run` | Print planned actions without creating anything                  |
| `--silent`  | Suppress progress output                                         |

## Tag mapping

KeePass group paths are converted to tags, with a tag added for each level of the hierarchy so items remain discoverable by parent group:

```
(no group)          → no tags
Email               → ["Email"]
Email/Work          → ["Email", "Email/Work"]
Development/Cloud   → ["Development", "Development/Cloud"]
```

## Password history

KeePass password history is replayed as real 1Password item history, visible in the UI via **View password history**:

1. The item is created with the **oldest** historical password.
2. The item is updated (`put()`) once per subsequent password, oldest → newest.
3. A final `put()` restores the **current** password.

Each `put()` call produces a genuine 1Password history entry. Items without history are bulk-created normally (no extra API calls). Timestamps from KeePass are not preserved — history entries will show the time the import ran.

## Resuming an interrupted import

If the import is interrupted, a `.import-state.json` file is written next to the input file. Re-run the exact same command to resume — completed items are skipped. The state file is deleted automatically on full success.

## Testing

A test XML file (`keepass-test-export.xml`) is provided. It covers logins, secure notes, TOTP, attachments, nested groups, password history with duplicates, and a Recycle Bin entry that should be skipped.

```bash
python import-from-keepass-xml.py \
  --input keepass-test-export.xml \
  --vault "KeePass Import" \
  --dry-run
```
