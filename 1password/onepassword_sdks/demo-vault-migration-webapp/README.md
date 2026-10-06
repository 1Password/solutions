# 1Password Vault Migration Tool

A self-hosted web application for migrating vaults between 1Password accounts. Built with the [1Password JavaScript SDK](https://developer.1password.com/docs/sdks/) (v0.5.0) and the [1Password CLI](https://developer.1password.com/docs/cli/get-started).

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
  - **Source**: read access to vaults and items
  - **Destination**: permission to create vaults and items

## Quick start

```bash
# Clone or download the project, then:
docker compose up -d
```

Open `https://localhost:3001` in your browser and accept the self-signed certificate warning.

To run it without Docker (Node.js 20 or later and the `op` CLI installed):

```bash
npm ci
npm start
```

### Settings

| Environment variable | Default | What it does |
|---|---|---|
| `HOST` | `127.0.0.1` | Interface the server listens on. The Docker image sets `0.0.0.0` inside the container; `docker-compose.yml` publishes the port on `127.0.0.1` only. |
| `PORT` | `3001` | HTTPS port |
| `LOG_DIR` | `./logs` | Where the migration log file is written |
| `MIGRATION_READ_CONCURRENCY` | `6` | How many source reads (item batches and attachment downloads) run at once. Lower it if the source account hits read rate limits. |
| `MIGRATION_BATCH_MAX_BYTES` | `1073741824` (1 GB) | Most attachment and document bytes in one batch. Items bigger than this are created one at a time. |
| `MIGRATION_DEBUG` | off | `1` turns on debug logging (secret values are always redacted) |

## Usage

1. Enter the service account tokens for your source and destination accounts, then click **Connect Accounts**.
2. A table of source vaults appears with item counts. Select vaults using the checkboxes.
3. Click **Migrate Selected** to start. Progress updates in real time per vault and per item, and also shows in the bar at the bottom of the screen, so you can scroll through a long vault list while it runs.
   - If you refresh or close the page, the migration keeps running on the server. Open the page again and it picks the migration back up, with its progress, Resume and Cancel. If it finished while the page was closed, you'll see the result. To start another migration after that, connect again: the tokens aren't kept.
4. Once complete, review the summary. Click **Download Logs** for a full breakdown including any failures.
5. Verify the migrated data in your destination account.

## How migration works

Migration runs in three phases per vault:

1. **Prepare**: Fetches all items from the source vault using batch `items.getAll()` in chunks of 50, including fields, sections, tags, websites, notes, file attachments, and document content. Several batches and attachment downloads run in parallel. For credit card items, the expiry date is recovered via the CLI since the SDK returns it as an unsupported field type. With service accounts, the next vault is read while the current one is being written.

2. **Create**: Batch-creates items in the destination vault using `items.createAll()`, up to 100 per batch. Items with attachments, documents and credit cards go in the batches too, since a batch counts as one write against the service account's rate limit however many items it holds. A batch also closes once its attachments add up to 1 GB (`MIGRATION_BATCH_MAX_BYTES`), and anything bigger than that is created on its own. If 1Password refuses a whole batch, it's split in half until the item causing it is found; an item that fails inside a batch gets one more try on its own before it's counted as failed. Reference fields are stripped during this phase to avoid invalid ID errors.

3. **Remap references**: For items that had Reference fields, the tool maps source item IDs to their new destination IDs, then adds the Reference fields back with the correct new IDs via `items.put()`, starting from the copy 1Password returned when the item was created (no extra read).

### Rate limits

1Password limits each service account token per hour (Business: 10,000 reads and 1,000 writes; Teams and Families: 1,000 reads and 100 writes) and each account per day. The destination's writes usually run out first.

- Before a migration starts, the tool reads the destination's live usage with `op service-account ratelimit` and tells you if the migration will need to pause.
- During the migration it checks again every 30 seconds or 25 requests, and before every request once it gets close. Live usage is shown under the progress bar.
- It pauses **before** a request would go over the limit, and shows a countdown to when the limit resets. When the countdown ends, click **Resume**: the limits are checked again before anything else is sent, and if there still isn't room it pauses again with a new countdown. **Cancel migration** stops it.
- Batches are shrunk to fit the room that's left. Batched creates are first assumed to count once per item; if 1Password's numbers show a batch counts once, the tool uses that and pauses less.
- If 1Password answers with a 429 anyway (for example another tool is using the same token), the affected items are put back in the queue and the migration pauses until the time 1Password gives, rather than failing them.
- If the browser tab is closed while paused, the migration resumes on its own once the limit resets.
- Desktop (app) authentication doesn't have service account limits, so none of this applies there.

### Category handling

| Source category | Destination handling |
|---|---|
| Login, Secure Note, API Credential, Server, SSH Key, Software License, Database, etc. | Migrated as-is with all fields preserved |
| Credit Card | Special handling: built-in fields assigned to root section, card type mapped to display names (e.g. `mc` → `Mastercard`), expiry recovered via CLI fallback, proper section ordering enforced |
| Document | Document content downloaded and re-uploaded with the item |
| **Custom / Unsupported** | **Converted to Login**: username, password, and OTP are detected by label/ID and mapped to Login built-in fields; all other fields placed in their original sections; concealed fields remain concealed |

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
├── webapp.js              # Express server and all migration logic
├── rate-limits.js         # Service account rate limit tracking, pause and resume
├── views/
│   ├── welcome.ejs        # Landing page
│   └── migration.ejs      # Migration UI (vault table, progress, logs)
├── Dockerfile             # Hardened Alpine Node.js + verified 1Password CLI
├── docker-compose.yml
├── package.json
└── README.md
```

## Architecture

- **Backend**: Node.js with Express, serving EJS templates over HTTPS (self-signed certificate via `selfsigned`)
- **Item operations**: 1Password SDK v0.5.0: `items.getAll()` and `items.createAll()` for batch reads/writes, `items.get()` and `items.create()` for individual items
- **Vault creation**: SDK `vaults.create()` with admins allowed to manage the vault (the same default as `op vault create`). The CLI is only used if the SDK reports it can't create vaults
- **Fewer calls**: connecting is one `vaults.list()` call (it includes item counts); each token signs in once and the client is reused across connects and migrations (signing in again automatically if the sign-in expires); a migrated vault is verified with `vaults.getOverview()` rather than listing every item
- **CLI**: `op item get` recovers credit card expiry dates the SDK returns as unsupported, and `op service-account ratelimit` reads live rate limits
- **Progress streaming**: Server-Sent Events for real-time updates to the browser
- **Rate limits**: live usage from `op service-account ratelimit`, pausing before the limit with a countdown and Resume (see [Rate limits](#rate-limits))
- **Error handling**: exponential backoff retry for data conflicts, per-item error tracking with detailed failure logs
- **Container image**: hardened for the fewest known vulnerabilities. Node.js 24 LTS on Alpine, with npm, yarn, the `apk` package manager and the busybox shell removed; it runs as a non-root user. Every build installs the newest stable 1Password CLI (from 1Password's update feed) and checks its signature against 1Password's release key; `docker compose up` rebuilds each time, so a new CLI release is picked up on the next start. To pin a version instead: `docker compose build --build-arg OP_VERSION=2.40.0`. Base images are pinned by digest, so rebuild regularly (or let Dependabot/Renovate bump the digests) to pick up security fixes
- **Container runtime** (`docker-compose.yml`): read-only filesystem, all Linux capabilities dropped, `no-new-privileges`, a process limit, and in-memory `/tmp` and home directory for the CLI. The migration log is kept in the `migration-logs` volume

## Security

- Runs on HTTPS with a self-signed TLS certificate
- Listens on `127.0.0.1` only by default, and refuses cross-site requests, because the web UI has no login
- Service account tokens are held in browser memory, and on the server only for the few seconds between starting a migration and its progress stream opening (and by the migration itself while it runs). They're never stored in the browser, so a refreshed page has to connect again
- What a refreshed page gets back about a running migration is vault names, item counts and progress, never tokens or item data
- Vault data (passwords, keys, files) is held in Node.js process memory during migration and released as each vault finishes
- The migration log is written to `logs/` (or `LOG_DIR`). It contains vault and item names and IDs, never secret values. Delete it, or click **Clear Logs**, when you're done
- `.env` and `logs/` are excluded from Docker images and git

## Limitations

- **Passkeys** cannot be migrated. Neither the SDK, CLI, nor vault export can access passkey fields
- **Archived items** are not migrated
- **Custom category items** are converted to Login items. Fields and sections are preserved but the category changes
- **Vault names** are appended with "(Migrated)" in the destination account
- **Reference fields** are only remapped within the same vault. Cross-vault references will not resolve
- The self-signed certificate is suitable for local use only

## Troubleshooting

- **Docker not starting**: Ensure Docker is installed and the daemon is running
- **Connection failures**: Verify service account tokens are valid with correct permissions (read for source, create for destination)
- **SSL warnings**: Expected with the self-signed certificate. Accept the warning for `localhost`
- **Paused for rate limits**: Expected for large migrations. Wait for the countdown and click Resume. If the countdown is many hours, the account's daily limit has been reached
- **"This op CLI can't report rate limits"**: Update the 1Password CLI; until then the tool only pauses after 1Password reports a limit
- **"Failed to convert to Item"**: Usually caused by unsupported field types or malformed values. Check the downloaded log for the specific item and field
- **Container logs**: Run `docker compose logs` for server-side output. The image has no shell, so `docker exec ... sh` won't work; `docker compose exec app node -e "..."` does if you need to look inside
