# 1Password Vault Migration Tool

A self-hosted web application for migrating vaults between 1Password accounts. Built with the [1Password JavaScript SDK](https://developer.1password.com/docs/sdks/) (v0.4.0-beta.2) and the [1Password CLI](https://developer.1password.com/docs/cli/get-started).

## Overview

The tool provides a browser-based interface to:

- Connect to source and destination 1Password accounts using service account tokens
- Browse and search source vaults with item counts
- Select specific vaults or migrate all at once
- Track migration progress in real time via Server-Sent Events
- Download detailed migration logs for auditing and troubleshooting

## Requirements

- [Docker](https://docs.docker.com/get-started/get-docker/) and Docker Compose
- Two [1Password service accounts](https://developer.1password.com/docs/service-accounts/get-started#create-a-service-account):
  - **Source** — read access to vaults and items
  - **Destination** — permission to create vaults and items

## Quick start

```bash
# Clone or download the project, then:
docker compose up -d
```

Open `https://localhost:3001` in your browser and accept the self-signed certificate warning.

## Usage

1. Enter the service account tokens for your source and destination accounts, then click **Connect Accounts**.
2. A table of source vaults appears with item counts. Select vaults using the checkboxes.
3. Click **Migrate Selected** to start. Progress updates in real time per vault and per item.
4. Once complete, review the summary. Click **Download Logs** for a full breakdown including any failures.
5. Verify the migrated data in your destination account.

## How migration works

Migration runs in three phases per vault:

1. **Prepare** — Fetches all items from the source vault using batch `items.getAll()` in chunks of 50, including fields, sections, tags, websites, notes, file attachments, and document content. For credit card items, the expiry date is recovered via the CLI since the SDK returns it as an unsupported field type.

2. **Create** — Batch-creates items in the destination vault using `items.createAll()` in chunks of 50. Items with binary content (files, documents) and credit card items are created individually since they require special handling. Reference fields are stripped during this phase to avoid invalid ID errors.

3. **Remap references** — For items that had Reference fields, the tool maps source item IDs to their new destination IDs, then adds the Reference fields back with the correct new IDs via `items.put()`.

### Category handling

| Source category | Destination handling |
|---|---|
| Login, Secure Note, API Credential, Server, SSH Key, Software License, Database, etc. | Migrated as-is with all fields preserved |
| Credit Card | Special handling: built-in fields assigned to root section, card type mapped to display names (e.g. `mc` → `Mastercard`), expiry recovered via CLI fallback, proper section ordering enforced |
| Document | Document content downloaded and re-uploaded individually |
| **Custom / Unsupported** | **Converted to Login** — username, password, and OTP are detected by label/ID and mapped to Login built-in fields; all other fields placed in their original sections; concealed fields remain concealed |

### What gets migrated

- All field types: Text, Concealed, TOTP, Address, SSH Key, Date, MonthYear, Email, Phone, URL, Menu, CreditCardType, CreditCardNumber, and Reference
- Sections (preserved in original order)
- File attachments (binary content)
- Document content
- Tags
- Website URLs with autofill behavior
- Notes

## Project structure

```
├── webapp.js              # Express server — all migration logic
├── views/
│   ├── welcome.ejs        # Landing page
│   └── migration.ejs      # Migration UI (vault table, progress, logs)
├── Dockerfile             # Node.js + 1Password CLI
├── docker-compose.yml
├── package.json
└── README.md
```

## Architecture

- **Backend**: Node.js with Express, serving EJS templates over HTTPS (self-signed certificate via `selfsigned`)
- **Item operations**: 1Password SDK v0.4.0-beta.2 — `items.getAll()` and `items.createAll()` for batch reads/writes, `items.get()` and `items.create()` for individual items
- **Vault creation**: 1Password CLI (`op vault create`) via `execSync`, since the SDK doesn't support vault creation
- **CLI fallback**: `op item get` used to recover credit card expiry dates that the SDK returns as unsupported
- **Progress streaming**: Server-Sent Events for real-time updates to the browser
- **Error handling**: Exponential backoff retry (3 attempts) for rate limits and data conflicts, per-item error tracking with detailed failure logs

## Security

- Runs on HTTPS with a self-signed TLS certificate
- Service account tokens are held in browser memory only — not persisted to disk or server-side storage
- All vault data (passwords, keys, files) is held in Node.js process memory during migration and released when the process exits — nothing is written to disk
- The application is designed to run locally with no authentication on the web UI

## Limitations

- **Passkeys** cannot be migrated — neither the SDK, CLI, nor vault export can access passkey fields
- **Archived items** are not migrated
- **Custom category items** are converted to Login items — fields and sections are preserved but the category changes
- **Vault names** are appended with "(Migrated)" in the destination account
- **Reference fields** are only remapped within the same vault — cross-vault references will not resolve
- The self-signed certificate is suitable for local use only

## Troubleshooting

- **Docker not starting**: Ensure Docker is installed and the daemon is running
- **Connection failures**: Verify service account tokens are valid with correct permissions (read for source, create for destination)
- **SSL warnings**: Expected with the self-signed certificate — accept the warning for `localhost`
- **Rate limit errors**: The tool retries automatically with exponential backoff
- **"Failed to convert to Item"**: Usually caused by unsupported field types or malformed values — check the downloaded log for the specific item and field
- **Container logs**: Run `docker logs <container-name>` for server-side output