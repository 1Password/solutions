# 1Password Encrypted Vault Backup App

This web app enables secure backup and restoration of 1Password vaults, encrypting the backup with a user-provided passcode and storing sensitive keys in a dedicated 1Password vault. It uses the 1Password JS SDK and CLI for vault operations, with encryption handled via Argon2 and AES-256-CBC.

## Overview

This app allows you to:
- Connect to a 1Password account using a service account token.
- List and select vaults for backup.
- Encrypt and save vault data to a downloadable file.
- Store encryption keys in a secure 1Password vault.
- Restore vaults from an encrypted backup file to a destination account.

## Requirements

- [Docker](https://docs.docker.com/get-started/get-docker/)
- [1Password Service Account](https://developer.1password.com/docs/service-accounts/get-started) with:
  - Read access for listing vaults and items (backup).
  - Vault creation and item creation permissions (restore).

## Installation

1. [Install Docker](https://docs.docker.com/get-started/get-docker/).
2. Clone or download this project.
3. Navigate to the project folder and run:

```
docker compose up -d
```

## Usage

### Backup
1. Open `https://localhost:3002` in your browser.
2. Click **Backup** in the sidebar.
3. Enter your 1Password service account token and click **Connect**.
4. Select vaults to back up and provide a passcode (minimum 8 characters).
5. Click **Backup Selected Vaults** or **Backup All Vaults**.
6. Save the generated encryption keys to a new 1Password vault or download them.
7. Download the encrypted `backup.1pbackup` file.

### Restore
1. Open `https://localhost:3002` and click **Restore**.
2. Upload the `backup.1pbackup` file and enter the service account token, passcode, and system key.
3. Select vaults to restore from the backup.
4. Click **Restore Selected Vaults**.
5. Verify the restored vaults in the destination account.

## Special Handling with CLI

- **Vault Creation**: Uses 1Password CLI (`op vault create`) to create new vaults for restored data and key storage, as vault creation is not supported by the SDK.

## Security Features

- Runs on HTTPS with a self-signed certificate (local testing).
- Uses Argon2 for key derivation and AES-256-CBC for backup encryption.
- Verifies backup integrity with HMAC-SHA256.
- Saves encryption keys (passcode and system key) in a secure 1Password vault.
- Uses `p-limit` to prevent overwhelming the 1Password API.
- Implements retry logic for API rate limits or conflicts.

## Troubleshooting

- Ensure Docker is running and the container is active (`docker logs <container-name>`).
- Verify service account token permissions (read for backup, create for restore/keys).
- Check `https://localhost:3002` is accessible; accept the self-signed certificate if prompted.
- Confirm passcode and system key match the backup file during restoration.
- Ensure the backup file is not corrupted or tampered with (HMAC verification failure).

## Limitations

- Passkeys cannot be backed up or restored (use 1Password desktop/mobile apps).
- SDK does not support archived items for backup/restore.
- Restored vault names are appended with "(Restored)".
- Fixed concurrency limits (2 vaults, 1 item at a time) may need tuning for large backups.