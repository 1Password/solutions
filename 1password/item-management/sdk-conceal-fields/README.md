# conceal_custom_fields.py

A Python script that makes every user-added custom field in your 1Password items **concealed** (the dotted/masked field type). Built-in fields like `username`, `password`, and `notesPlain` are left alone.

The script creates a short-lived service account scoped to vaults you have Manage permission on, stores the SA token as a Password item in your personal vault for easy retrieval, then uses the [1Password Python SDK](https://developer.1password.com/docs/sdks/) to walk every item and flip eligible custom fields to `CONCEALED`.

## Requirements

- Python 3.10+
- [`onepassword-sdk`](https://pypi.org/project/onepassword-sdk/) (`pip install onepassword-sdk`)
- [1Password CLI](https://developer.1password.com/docs/cli/get-started/) v2.18.0 or later, installed and signed in (only required for _bootstrap mode_ — see below)
- Permission on your 1Password account to create service accounts (ask your admin if the option isn't visible to you)

## Two modes

### Bootstrap mode (default)

When run with no token, the script:

1. Calls `op whoami` to identify the signed-in user.
2. Lists every vault and checks (in parallel) which ones the user has Manage permission on, excluding built-in vaults service accounts can't access.
3. With `--apply`: creates a service account named `conceal-custom-fields-<timestamp>` with `read_items,write_items` on each manageable vault and a default 1-hour expiry.
4. Saves the SA token as a Password item in your personal vault (Private / Personal / Employee, whichever the script finds) tagged `conceal-custom-fields`.
5. Uses the SDK with that token to conceal eligible custom fields.

### Reuse mode (`--token` or `OP_SERVICE_ACCOUNT_TOKEN`)

When a token is provided, the script skips the CLI entirely:

1. Authenticates the SDK with the supplied token.
2. Lists every vault the token can see via `client.vaults.list()`.
3. Walks each vault, previewing or writing depending on `--apply`.

This is the way to do a true field-level dry-run, since the SA already exists.

## Retrieving a saved token

After a successful bootstrap with `--apply`, the script prints a ready-to-paste command:

```bash
OP_SERVICE_ACCOUNT_TOKEN=$(op read 'op://Personal/conceal-custom-fields-20260515-123456/password') \
    python conceal_custom_fields.py --apply
```

Or just open the item in 1Password — it's tagged `conceal-custom-fields` and titled with the SA's name, with a note describing what it is and when it expires. The token lives in the item's password field. Once the SA expires (1 hour by default) the item is useless — delete it.

## Usage

```bash
# Bootstrap, preview only — lists which vaults qualify; no SA is created.
python conceal_custom_fields.py

# Bootstrap, commit — creates a 1-hour SA, saves the token, writes changes.
python conceal_custom_fields.py --apply

# Bootstrap with custom SA name, longer expiry, and a specific token vault.
python conceal_custom_fields.py --apply \
    --sa-name audit-2026 --sa-expires-in 24h \
    --save-token-to-vault MyOps

# Bootstrap without persisting the token (one-shot use).
python conceal_custom_fields.py --apply --no-save-token

# Tune parallelism for the permission-discovery step (default 10).
python conceal_custom_fields.py --apply --concurrency 20

# Reuse an existing SA token — previews every field change.
python conceal_custom_fields.py --token ops_xxx...

# Reuse and commit.
python conceal_custom_fields.py --token ops_xxx... --apply

# Reuse via env var (matches the SDK's own convention).
export OP_SERVICE_ACCOUNT_TOKEN=ops_xxx...
python conceal_custom_fields.py --apply
```

## Flags

| Flag                          | Default                             | Notes                                                                                                                         |
| ----------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `--apply`                     | off                                 | Without this, the script previews and exits. In bootstrap mode this is also what triggers SA creation.                        |
| `--token TOKEN`               | —                                   | Use this SA token. Falls back to `OP_SERVICE_ACCOUNT_TOKEN` if not given.                                                     |
| `--sa-name NAME`              | `conceal-custom-fields-<timestamp>` | Bootstrap mode only.                                                                                                          |
| `--sa-expires-in DURATION`    | `1h`                                | Bootstrap mode only. Go duration format (`30m`, `1h`, `24h`).                                                                 |
| `--save-token-to-vault VAULT` | auto-detect                         | Bootstrap mode only. Vault where the new SA's token is stored as a Password item. Default: try Private → Personal → Employee. |
| `--no-save-token`             | off                                 | Bootstrap mode only. Skip saving the token; use it in-memory only.                                                            |
| `--concurrency N`             | `10`                                | Bootstrap mode only. Parallel `op vault user list` calls.                                                                     |

## What counts as a "custom field"

Any field whose `id` is **not** one of the well-known built-in ids 1Password reserves (`username`, `password`, `notesPlain`, `cardholder`, `ccnum`, etc. — the full list is in `BUILTIN_FIELD_IDS` near the top of the script). Custom fields get random 26-character ids, so the filter is robust across item categories.

The script also refuses to coerce field types where flipping to `CONCEALED` would corrupt or drop data: TOTP, SSH keys, addresses, dates, month/year, references, menus, credit-card-specific types, and files. These are listed in `NON_COERCIBLE_TYPES` and you can adjust either set if your situation differs.

## Caveats

**Service accounts can't access Personal, Private, Employee, or default Shared vaults.** This is a 1Password rule, not a script choice. Items in those vaults will be silently skipped by the concealment pass. (The script _writes_ the token item to your personal vault using your own auth, which is fine — only the SA is restricted.) If you have custom fields in personal vaults, run an SDK-only variant against them using desktop-app auth.

**Service-account permissions are immutable after creation.** If you create vaults later or need different access, you'll need to create another SA. The script defaults to a short expiry so abandoned SAs clean themselves up.

**The token is saved to 1Password before concealment runs.** That ordering is deliberate — if concealment fails partway through, the token is still recoverable and you can retry. The trade-off: if the `op item create` call fails, the script falls back to printing the token to stdout so you don't lose it.

**Service accounts can't be deleted via the CLI.** Either let the expiry handle it or revoke manually in the web UI (`1password.com → Developer → Service Accounts`). 1Password limits accounts to 100 service accounts total, so don't loop the script in tests without short expiries. The saved token item lingers too — delete it manually once it's no longer useful.

**Type changes are non-destructive but visible.** Flipping `TEXT → CONCEALED` doesn't lose the underlying value, but the field becomes masked in the UI and won't show in plain text again without revealing it. Review the dry-run carefully before applying.

## Troubleshooting

**`op whoami` fails** — make sure the 1Password CLI is installed, v2.18.0+, and you're signed in (`eval $(op signin)` or via the desktop-app integration).

**No vaults are discovered as manageable** — you need the Manage Vault permission on at least one non-built-in vault. Owners have it implicitly; everyone else needs it granted by an admin.

**`Could not auto-detect a personal vault`** — your account doesn't have a vault named Private, Personal, or Employee. Pass `--save-token-to-vault VAULT_NAME` to specify, or `--no-save-token` to use the SA in-memory only.

**`Could not create service account`** — possible causes: your account doesn't allow you to create SAs, you've hit the 100-SA cap, or your plan doesn't support service accounts. The CLI's error message will say which.

**`put() failed` on specific items** — most often this means the item contains an `UNSUPPORTED` field type the SDK can't round-trip (very old MonthYear or OTP fields can do this). The script tries to detect these up-front and skip the item, but if one slips through the error is reported and the script continues to the next item.

**Vault permission discovery is slow** — turn up `--concurrency`. 10 is conservative; 25–50 is fine for most accounts. The 1Password CLI has rate limits but they're generous for read-only metadata calls.

## Customizing what gets concealed

The two main knobs are at the top of the script:

- `BUILTIN_FIELD_IDS` — add ids here to leave them alone. Useful if you have category-specific built-ins this script doesn't already know about.
- `NON_COERCIBLE_TYPES` — add `ItemFieldType` members here to refuse to convert those types.

To narrow to _only_ plain-text fields (leave URLs and emails as their original type even if they're custom), add this guard in `process_item`:

```python
if field.field_type not in {ItemFieldType.TEXT, ItemFieldType.STRING}:
    continue
```
