# Vault permission scripts (PowerShell)

These three scripts help you copy vault access from one 1Password account to another, and lock vaults down to view only. They don't touch anything stored in the vaults. They only look at, or change, who has access and what they can do.

These are the ones to use on Windows. There are Python versions in `../python`, but those are only for macOS and Linux. Both versions work the same way and make the same CSV.

## Before you start

You'll need:

- PowerShell 7 or newer (`pwsh`). Windows PowerShell 5.1 won't work, because the scripts use `ForEach-Object -Parallel`. PowerShell 7 runs on Windows, Mac and Linux.
- The 1Password CLI (`op`), version 2.25 or newer. See [Get started with 1Password CLI](https://developer.1password.com/docs/cli/get-started/) for how to install it. On Windows, `winget install AgileBits.1Password.CLI` is the quickest way. Open a new PowerShell window afterwards so it picks up `op`.
- To be signed in as an **Owner**, meaning someone in the Owners group. Owners can see and manage every vault, group and person, so nothing gets missed. If you run these as anyone else, vaults they can't manage won't show up and changes to them will fail.

## Signing in on Windows

On Windows, use the manual sign-in instead of the 1Password app integration. Do it in the same PowerShell window you'll run the scripts from.

The first time, add your account to the CLI:

```powershell
op account add --address yourcompany.1password.com --email you@yourcompany.com
```

Then sign in. The `Invoke-Expression` part matters, because it saves the session in the window so the scripts can use it:

```powershell
Invoke-Expression $(op signin --account yourcompany)
```

Check it worked and that you're signed in as the Owner:

```powershell
op whoami
```

The session ends after 30 minutes of not using the CLI, and it only lasts as long as that window. If a script says you're not signed in, run the `Invoke-Expression` line again and start the script over.

On macOS or Linux you can use the app integration instead (in the 1Password app, go to Settings > Developer and turn on "Integrate with 1Password CLI"), and then you don't need these steps.

If you're signed in to more than one account, add `-Account yourcompany` to any of the scripts to pick the right one.

Every script has built-in help, so you can always check the options with:

```powershell
Get-Help ./recreate_vault_permissions.ps1 -Full
```

If Windows won't run the scripts because of the execution policy, run this once in the same window:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## The usual order

If you're moving vaults to a new account, it goes like this:

1. Sign in to the **old** account and run `shared_vaults_permissions_mapping.ps1`. You get `vault_access_report.csv`.
2. Migrate the vaults. Copies often end up named something like `Finance (Migrated)`, and that's fine.
3. Sign in to the **new** account and run `recreate_vault_permissions.ps1`. It reads the CSV and sets the same access up again.

`lockdown_view_only.ps1` is a separate job. Use it when you want everyone on the vaults to have view only access, for example while a migration is happening so nobody edits anything halfway through.

## shared_vaults_permissions_mapping.ps1

Writes down who has access to every vault you can manage, and what they can do.

```powershell
./shared_vaults_permissions_mapping.ps1
./shared_vaults_permissions_mapping.ps1 -File vault-ids.txt -Account mycompany
```

- The results always go to `vault_access_report.csv` in this folder.
- `-File` is optional. It's a plain text file you write yourself with one vault ID per line, if you only want to check some vaults. It's only read.
- Each row is one person on one vault. People added straight to a vault show as `Direct`. People who get access through a group get a row each, marked `Group (Name)`.
- The Employee vault is skipped.

If some vaults can't be read, the CSV still gets written, but you'll see a warning, the details go in `logs/mapping_<timestamp>/errors.log`, and the script exits with 1. Fix the problem and run it again before relying on the CSV.

The CSV is exactly the same as the one the Python version makes, so you can make it with one and read it with the other.

**Heads up:** the CSV has names and email addresses in it, so don't commit it to git.

## recreate_vault_permissions.ps1

Reads the CSV and gives the same people and groups the same permissions on the matching vaults in whatever account you're signed in to.

```powershell
./recreate_vault_permissions.ps1 -DryRun
./recreate_vault_permissions.ps1 -CreateGroups
./recreate_vault_permissions.ps1 -File ./access.csv -NoCreateGroups
```

| Option | What it does |
|---|---|
| `-File` | The CSV to read. Defaults to `vault_access_report.csv` in this folder. |
| `-Account` | Which account to use, if you're signed in to more than one. |
| `-CreateGroups` | Create any groups that are missing, add their members, then do the vault access. |
| `-NoCreateGroups` | Never create groups and don't ask. |
| `-DryRun` | Show what would happen without changing anything. |

If you don't pass either group option, it asks you when it finds missing groups.

How it matches things up:

- Everything is matched by name. IDs in the CSV are ignored, since they're different in the new account.
- Vaults are matched by name, with `(Migrated)` on the end ignored. So `Finance` in the CSV matches `Finance (Migrated)`. If both exist, it uses the `(Migrated)` one.
- People are matched by email, and groups by name.
- Built-in groups (Recovery, Team Members, Administrators, Provision Managers, Security and Owners) are never created. They already exist in every account. The Recovery group's access is always skipped because 1Password looks after that itself.
- It only ever adds permissions. It never takes any away, so it's safe to run more than once.

Anything it couldn't do, like a vault, person or group that doesn't exist, or a change that failed, gets a short summary at the end instead of a wall of red errors. The full list is in `logs/recreate_<timestamp>/not_recreated.csv`, and every change it made is in `audit.log` in the same folder. It only exits with 1 if something actually failed. Missing people or vaults on their own don't count.

Always do a `-DryRun` first.

## lockdown_view_only.ps1

Brings everyone on your vaults down to view only.

```powershell
./lockdown_view_only.ps1 -DryRun
./lockdown_view_only.ps1 -Account mycompany
```

- Anyone added straight to a vault, and any group on a vault, ends up with `allow_viewing` and nothing else.
- It gives view access first and then removes the rest, so nobody gets locked out in between.
- It leaves the Recovery, Administrators, Owners, Provision Managers and Security groups alone, plus the Employee vault, so you can still run the account.
- Anyone who's already view only gets skipped, so you can run it again safely.
- If the CLI isn't signed in, it signs you in using `-Account`, then the `OP_ACCOUNT` environment variable, then asks you. This works with the manual sign-in too, and the session stays in the window afterwards. The other two scripts don't do this, so for those, sign in first as shown in [Signing in on Windows](#signing-in-on-windows).

Every change, retry and failure goes in `logs/<timestamp>/errors.log`. Anything that still failed also goes in `failed_changes.jsonl`.

This is written for 1Password Teams, which has three permission levels: view, edit and manage.

## How they run

- **Several at once.** The mapping and recreate scripts work on 10 things at a time. Lockdown does 5. That's set near the top of each script (`$Threads`) if you need to change it.
- **Retries.** If an `op` command fails, it's tried again a few times with a short wait in between. Errors that won't fix themselves, like "not found", aren't retried.
- **Logs.** Everything goes in a `logs` folder next to the scripts, with a new folder for each run. Like the CSV, the logs can have names and emails in them.
- **Colours.** You only get colours when running in a terminal. Set `$env:NO_COLOR = 1` to turn them off.

## Rate limits

1Password limits how fast you can make changes. On a big account, the recreate script makes one change per person or group per vault, so it can add up fast. If you start seeing "too many requests" errors, lower `$Threads` and run it again. It skips anything that's already done.

If you use a service account, it also has hourly limits. Business accounts get 1,000 changes an hour and Teams accounts get 100.
