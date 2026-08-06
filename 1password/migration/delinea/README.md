# Delinea CSV → 1Password Vault Import

Creates a new 1Password vault named `Delinea Export - YYYY-MM-DD` and
bulk-creates one item per secret from a Delinea (Secret Server) CSV export,
using the official 1Password Python SDK and its batch item-creation API
(`items.create_all`, up to 100 items per call).

Run it directly on a server with Python, or as a Docker container.

## 1. Create a service account

1. Sign in to your 1Password account and open **Developer** → **Service Accounts**.
2. Create a new service account.
3. **Important:** grant it the **"Create Vaults"** permission. Without it,
   vault creation will fail with a permissions error. (Service accounts are
   scoped per-vault and can't update or delete vaults they didn't create —
   see [1Password's docs on managing vaults with SDKs](https://developer.1password.com/docs/sdks/vaults).)
4. Save the generated token somewhere secure (your OS keychain, your CI
   provider's secret store, a `.env` file that's `chmod 600` and git-ignored,
   etc.) — **not** in a file that gets committed, and avoid passing it as a
   literal `-e OP_SERVICE_ACCOUNT_TOKEN=ops_...` on a command line, since that
   lands in shell history and is visible to anyone who can run `ps` on the
   host or `docker inspect` the container. Prefer an env file or your
   platform's secrets manager (see the Docker section below).

This service account token is the bootstrap credential the script uses to
talk to 1Password in the first place, so it can't itself be replaced with an
`op://` secret reference — nothing has authenticated yet to resolve one. Every
other secret in this workflow (the Delinea passwords) ends up safely inside
1Password, which is the actual point of running this script.

---

## Option A: Run directly on a server (Python)

### A1. Install dependencies

```bash
pip install -r requirements.txt
```

### A2. Set the service account token

```bash
export OP_SERVICE_ACCOUNT_TOKEN="ops_..."
```

Or, better for a long-lived server: put it in a `chmod 600` file (e.g.
`/etc/delinea-import/token.env`) containing `OP_SERVICE_ACCOUNT_TOKEN=ops_...`
and load it with `set -a; source /etc/delinea-import/token.env; set +a`
immediately before running the script, rather than exporting it in a shell
profile where it lingers.

### A3. Run it

```bash
python delinea-csv-to-1p-vault.py --csv secrets-export.csv --dry-run   # preview
python delinea-csv-to-1p-vault.py --csv secrets-export.csv             # real run
```

See [Column mapping / dry run](#column-mapping--dry-run) and [Options](#options) below.

---

## Option B: Run with Docker

### B1. Build the image

```bash
docker build -t delinea-to-1password .
```

### B2. Put your export somewhere the container can read it

The image expects your CSV to be bind-mounted in, e.g. into `/data`:

```bash
mkdir -p ./data
cp /path/to/secrets-export.csv ./data/
```

### B3. Preview the mapping (no token needed, no 1Password access)

```bash
docker run --rm -v "$(pwd)/data:/data:ro" delinea-to-1password \
  --csv /data/secrets-export.csv --dry-run
```

### B4. Run the real import

Pass the token via `--env-file` (a git-ignored file, `chmod 600`), not
`-e OP_SERVICE_ACCOUNT_TOKEN=...` inline, so it never touches your shell
history or `docker inspect` output:

```bash
echo "OP_SERVICE_ACCOUNT_TOKEN=ops_..." > .env.token
chmod 600 .env.token

docker run --rm \
  --env-file .env.token \
  -v "$(pwd)/data:/data:ro" \
  delinea-to-1password \
  --csv /data/secrets-export.csv
```

On Docker Swarm or Kubernetes, prefer native secrets (`docker secret`, a
Kubernetes `Secret` mounted as a file/env var) over `--env-file` for anything
beyond local/manual runs.

### B5. Or use docker-compose

```bash
mkdir -p ./data && cp /path/to/secrets-export.csv ./data/
echo "OP_SERVICE_ACCOUNT_TOKEN=ops_..." > .env   # git-ignored, chmod 600
chmod 600 .env

docker compose run --rm import --csv /data/secrets-export.csv --dry-run
docker compose run --rm import --csv /data/secrets-export.csv
```

`docker-compose.yml` builds the image, mounts `./data` read-only into
`/data`, and reads `OP_SERVICE_ACCOUNT_TOKEN` from your `.env` file
automatically (`docker compose` loads `.env` in the working directory by
convention — make sure it's git-ignored).

### Notes for running as a scheduled/server-side job

- The container is intentionally a one-shot job (`ENTRYPOINT` + args), not a
  long-running service — it creates one vault and exits. Trigger it from
  cron, a CI pipeline, a Kubernetes `Job`/`CronJob`, or similar.
- It runs as a non-root user (`uid 1000`) inside the image.
- Mount export files read-only (`:ro`) since the script never needs to write
  back to the CSV.
- Nothing is persisted inside the container between runs — vault/item state
  lives in 1Password, not on local disk — so it's safe to run from an
  immutable/ephemeral image on every invocation.

---

## Column mapping / dry run

```bash
python delinea-csv-to-1p-vault.py --csv your_export.csv --dry-run
# or: docker run --rm -v "$(pwd)/data:/data:ro" delinea-to-1password --csv /data/your_export.csv --dry-run
```

This prints how the script's column-detection matched your CSV's headers
without creating anything.

### Important: Delinea's multi-template export format

Secret Server does **not** export multiple templates as one CSV with a
single fixed header. Instead, every secret is its own two-line block: a
header row (always starting with `Secret Name`) listing that secret's
columns, immediately followed by one data row using those columns. The next
secret can have a completely different set of columns if it uses a different
template. For example:

```
Secret Name,Domain,Username,Password,Notes,Location,Server List,URL,Folder,TOTP Key,TOTP Backup Codes
Sample AD Account,example.com,jdoe,SamplePassword123!,,,,,\Sample Export\Folder 1\Subfolder 1,,
Secret Name,Host,Username,Password,Notes,Priviledge Level,DeviceModel,Folder,TOTP Key,TOTP Backup Codes,
Sample Cisco Account,host01.example.com,mchen,ThirdSample789#,,,,\Sample Export\Folder 1\Subfolder 1\Subfolder 2,,,
```

The script parses this shape directly (a plain `csv.DictReader` over the
whole file would misread it) and recomputes the column mapping **per
secret**, so mixed templates in a single export are handled correctly. The
`--dry-run` output groups secrets by their distinct column layout so you can
see exactly how each template's columns were interpreted.

Column matching is case-insensitive and covers common variants:

| Canonical field | Matches columns like                             |
| --------------- | ------------------------------------------------ |
| title           | Secret Name, Name, Title                         |
| domain          | Domain                                           |
| server          | Machine, Server, Host, IP Address, Resource Name |
| username        | Username, User, Account, Login                   |
| password        | Password, Secret                                 |
| url             | URL, Website, Connection String                  |
| notes           | Notes, Comment(s), Description                   |
| folder          | Folder(Path)                                     |
| template        | Secret Template (Name), Type                     |
| totp            | TOTP Key, TOTP Secret, OTP                       |

`TOTP Key` becomes a real one-time-password field in the created item (1Password
accepts a raw base32 seed directly). Any column that doesn't match one of
these — `Location`, `Server List`, `Priviledge Level`, `DeviceModel`, `Site
ID`, `TOTP Backup Codes`, etc. — ends up as a custom text field under a
"Delinea Details" section on the item, so nothing from the export is ever
silently dropped, even for templates the script doesn't specifically know
about.

## Options

- `--vault-title "..."` — override the default `Delinea Export - YYYY-MM-DD` name.
- `--vault-description "..."` — set a custom vault description.
- `--category LOGIN` — the 1Password item category to create rows as
  (default `LOGIN`, since most Delinea account templates are username/password
  credentials; also common: `SERVER`, `PASSWORD`).
- `--dry-run` — preview the mapping without contacting 1Password.

The script will:

1. Create the vault.
2. Build one `ItemCreateParams` per secret (password fields are marked
   `CONCEALED`, TOTP keys become real one-time-password fields, matching
   1Password's field-type model).
3. Send items to 1Password in batches of up to 100 via `items.create_all()`.
4. Print per-item success/failure and a final summary, tagging every
   imported item `delinea-import` (plus its original Delinea folder path and
   template name as extra tags) so it's easy to find or filter later.

## Files

- `delinea-csv-to-1p-vault.py` — the script.
- `requirements.txt` — Python dependencies.
- `Dockerfile` — builds a runnable image (non-root, one-shot job).
- `docker-compose.yml` — convenience wrapper for `docker run` with a mounted
  data directory and `.env`-sourced token.
- `.dockerignore` — keeps the build context small.
- `data.csv` — a sample multi-template export (five different secret
  templates, five different column layouts) you can run `--dry-run` against
  to see the mapping in action before pointing this at your own file.

## Notes / caveats

- 1Password's SDK batch limit is 100 items per `create_all()` call; the
  script chunks automatically if your export has more rows than that.
- The `--category` you pick determines the item's icon/category in 1Password,
  but field IDs are assigned generically (`username`, `password`, `server`)
  rather than category-specific built-ins, so double-check field labels after
  import if you need pixel-perfect category behavior (e.g. autofill).
- If item creation fails with a permissions error, confirm the service
  account has Read & Write on the vault (this should be automatic for a
  vault it just created, but is worth checking in **Developer** →
  **Service Accounts** → the account's Vaults table).
