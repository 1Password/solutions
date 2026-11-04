<#
.SYNOPSIS
    Brings every user and group on your vaults down to view only access.

.DESCRIPTION
    Checks every vault you can manage, or only the vaults in a CSV with -File. Anyone assigned directly, and any group assigned, ends up
    with view access and nothing else. Which permission that is depends on the account, and the
    script checks the account type before changing anything:

      Business  view_items. They can see the items, but can't reveal or copy passwords, see item
                history, or change anything.
      Teams     allow_viewing, since Teams only has allow_viewing, allow_editing and
                allow_managing. They can see the items and can reveal and copy passwords, but
                can't change anything or manage the vault.

    Everything else is revoked first, then the view permission is granted. The view permission
    itself is never revoked, so anyone who already has it keeps access throughout. Anyone who
    didn't have it is off the vault briefly between the two steps, and a failed grant there is
    reported as a failure.

    Left alone on purpose: the Recovery, Administrators, Owners, Provision Managers and Security
    groups, since changing them would get in the way of running the account, and the Employee
    vault.

    It's safe to run more than once. Current permissions are checked first, and anyone already
    view only is left as is. Work runs 5 at a time and each op command gets up to 5 tries.

    Every change, retry and failure goes in logs\<timestamp>\errors.log, and failures also go in
    failed_changes.jsonl.

.PARAMETER File
    A CSV of the vaults to lock down. Leave it out to lock down every vault you can manage.
    It needs a vaultName or vaultUUID column
    (name, vault, id and uuid work too, in any case), and if there's an include column, only rows
    set to yes are used. The vault_access_report.csv from shared_vaults_permissions_mapping.ps1
    works as is. Rows that don't match a vault you can
    manage are listed and skipped.

    If the CSV also lists who was assigned (an email column, plus assignment and groupName, as in
    vault_access_report.csv), anyone listed who's no longer on the vault is added back with
    the view permission: users assigned directly as users, and groups as groups. Group members aren't
    added one by one, since they get access through the group. The groups this script leaves
    alone are skipped here too.

.PARAMETER Account
    The 1Password account to sign in to, only used if the CLI isn't already signed in.
    Falls back to the OP_ACCOUNT environment variable, then asks.

.PARAMETER DryRun
    Show what would change without granting or revoking anything.

.EXAMPLE
    ./lockdown_view_only.ps1 -DryRun

    Shows who would be changed.

.EXAMPLE
    ./lockdown_view_only.ps1 -File ./vaults.csv -DryRun

    Shows who would be changed on just the vaults set to yes in vaults.csv.

.EXAMPLE
    ./lockdown_view_only.ps1 -Account mycompany

    Locks down the mycompany account's vaults.

.NOTES
    Works on 1Password Business and Teams. The account type comes from op account get, and if
    that doesn't say, from whether the vault list works with manage_vault (Business) or only
    allow_managing (Teams). Requires PowerShell 7 or later and the 1Password CLI.
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$File,
    [string]$Account,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Threads = 5
# What everyone ends up with, by account type. Set in Main once the account type is known.
$ViewPermissions = @{ Business = "view_items"; Teams = "allow_viewing" }
$TargetPermission = $null
$AccountType = $null
# Business accounts can report a whole level instead of the permissions in it, so levels are
# expanded there and revoking "everything else" never takes view_items away with a level. Teams
# only has the levels, so any granular names are folded back into their level instead.
$PermissionLevels = @{
    allow_viewing  = @("view_items", "view_and_copy_passwords", "view_item_history")
    allow_editing  = @("create_items", "edit_items", "archive_items", "delete_items", "import_items",
                       "export_items", "copy_and_share_items", "print_items")
    allow_managing = @("manage_vault")
}
$IgnoredVaultName = "employee"
$IgnoredGroupNames = @("recovery", "administrators", "owners", "provision managers", "security")
$YesValues = @("yes", "y", "true", "1", "x")
$ColumnNames = [ordered]@{
    include   = @("include")
    vaultName = @("vaultname", "name", "vault")
    vaultUUID = @("vaultuuid", "vaultid", "uuid", "id")
    email      = @("email", "useremail")
    assignment = @("assignment")
    groupName  = @("groupname")
}

$OpConfig = @{
    Account         = $null
    MaxRetries      = 4
    TimeoutSeconds  = 30
    PermanentErrors = @("does not have access", "not found", "isn't a vault", "isn't a group", "isn't a user",
                        "isn't a member", "not authorized", "no accounts for filter")
}

$IsTty = -not [Console]::IsOutputRedirected
$UseColor = $IsTty -and -not $env:NO_COLOR
$Bold, $Dim, $Red, $Green, $Yellow, $Cyan, $Reset = if ($UseColor) {
    "`e[1m", "`e[2m", "`e[91m", "`e[92m", "`e[93m", "`e[96m", "`e[0m"
} else { "", "", "", "", "", "", "" }

$RunStarted = Get-Date
$LogsDir = Join-Path $PSScriptRoot "logs" $RunStarted.ToString("yyyy-MM-dd_HH-mm-ss")
$FailedPath = Join-Path $LogsDir "failed_changes.jsonl"
$ErrorsLogPath = Join-Path $LogsDir "errors.log"
$script:Progress = @{ Label = ""; Done = 0; Total = 0 }


# Runs an op command, retrying up to MaxRetries times unless the error won't go away
function Invoke-Op {
    param([string[]]$Arguments, [string]$What, [hashtable]$Config)
    $err = ""
    $retries = [System.Collections.Generic.List[object]]::new()
    for ($attempt = 0; $attempt -le $Config.MaxRetries; $attempt++) {
        try {
            $psi = [System.Diagnostics.ProcessStartInfo]::new("op")
            foreach ($arg in $Arguments) { $psi.ArgumentList.Add($arg) }
            if ($Config.Account) { $psi.ArgumentList.Add("--account"); $psi.ArgumentList.Add($Config.Account) }
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.UseShellExecute = $false
            $process = [System.Diagnostics.Process]::Start($psi)
            $stdout = $process.StandardOutput.ReadToEndAsync()
            $stderr = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit($Config.TimeoutSeconds * 1000)) {
                $process.Kill($true)
                $err = "timed out after $($Config.TimeoutSeconds)s"
            } elseif ($process.ExitCode -eq 0) {
                return [pscustomobject]@{ Ok = $true; Out = $stdout.Result; Err = ""; Retries = $retries }
            } else {
                $err = $stderr.Result.Trim() -replace '^\[ERROR\]\s*(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\s*)?', ''
            }
        } catch {
            $err = $_.Exception.Message
        }
        $permanent = $Config.PermanentErrors | Where-Object { $err.ToLower().Contains($_) }
        if ($attempt -eq $Config.MaxRetries -or $permanent) { break }
        $retries.Add([pscustomobject]@{ Attempt = $attempt + 1; What = $What; Err = $err })
        Start-Sleep -Seconds ([math]::Pow(2, $attempt + 1))
    }
    return [pscustomobject]@{ Ok = $false; Out = ""; Err = $err; Retries = $retries }
}


# Turns op's JSON output into a list, treating empty output as an empty list
function ConvertFrom-OpJson {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return @() }
    return @($Text | ConvertFrom-Json | Where-Object { $null -ne $_ })   # op prints null for an empty list
}


# Prints an error and stops the script
function Stop-Script {
    param([string]$Message)
    [Console]::Error.WriteLine("$Red$Message$Reset")
    exit 1
}


# Draws the progress bar on the current line, only when running in a terminal
function Show-Progress {
    if (-not $IsTty -or -not $script:Progress.Total) { return }
    $width = 24
    $filled = [int][math]::Floor($width * $script:Progress.Done / $script:Progress.Total)
    $bar = ("█" * $filled) + ("░" * ($width - $filled))
    Write-Host ("`r  {0,-22} $Cyan{1}$Reset {2}/{3}`e[K" -f $script:Progress.Label, $bar, $script:Progress.Done, $script:Progress.Total) -NoNewline
}


# Starts a new progress bar
function Start-Progress {
    param([string]$Label, [int]$Total)
    $script:Progress = @{ Label = $Label; Done = 0; Total = $Total }
    Show-Progress
}


# Moves the progress bar forward by one
function Step-Progress {
    $script:Progress.Done++
    Show-Progress
}


# Clears the progress bar, and leaves a finished line in its place if there's one to show
function Stop-Progress {
    param([string]$Result)
    if ($IsTty -and $script:Progress.Total) { Write-Host "`r`e[K" -NoNewline }
    if ($Result) { Write-Host ("  {0,-22} {1}" -f $script:Progress.Label, $Result) }
    $script:Progress.Total = 0
}


# Prints above the progress bar so the two don't get mixed up
function Write-Say {
    param([string]$Text)
    if ($IsTty -and $script:Progress.Total) { Write-Host "`r`e[K" -NoNewline }
    Write-Host $Text
    Show-Progress
}


# Prints a section heading
function Write-Heading {
    param([string]$Title)
    Write-Host "`n$Bold$Title$Reset"
}


# Adds a timestamped line to errors.log, which keeps every change, retry and failure from the run
function Write-Log {
    param([string]$Message)
    Add-Content -Path $ErrorsLogPath -Value ("{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -Encoding utf8
}


# Records the retries an op command needed
function Write-Retries {
    param($Retries)
    foreach ($r in $Retries) { Write-Log "retrying $($r.What) (attempt $($r.Attempt)/$($OpConfig.MaxRetries + 1)): $($r.Err)" }
}


# Records a change that failed, on screen and in both log files
function Write-Failure {
    param([string]$Vault, [string]$TargetType, [string]$Target, [string]$Reason)
    Write-Log "failed: $Vault / ${TargetType}:${Target}: $Reason"
    $entry = [ordered]@{
        timestamp = (Get-Date).ToUniversalTime().ToString("o"); vault = $Vault
        target_type = $TargetType; target = $Target; reason = $Reason
    }
    Add-Content -Path $FailedPath -Value ($entry | ConvertTo-Json -Compress) -Encoding utf8
    Write-Say "  $Red✗ $Bold$Vault$Reset  $Dim${TargetType}: $Target$Reset`n      $Red$Reason$Reset"
}


# Manual sign-in prints the session instead of saving it, so this saves it for the op commands we run
function Save-Session {
    param([string]$SigninOutput)
    foreach ($m in [regex]::Matches($SigninOutput, '(OP_SESSION_\w+)\s*=\s*["'']?([^"''\s]+)')) {
        [Environment]::SetEnvironmentVariable($m.Groups[1].Value, $m.Groups[2].Value)
    }
}


# Reuses the CLI's session if it's signed in, otherwise signs in and passes --account from then on
function Connect-Account {
    $r = Invoke-Op -Arguments @("whoami", "--format=json") -What "whoami" -Config @{ MaxRetries = 0; TimeoutSeconds = 15; PermanentErrors = @() }
    if ($r.Ok) { return $r.Out | ConvertFrom-Json }

    $acct = if ($Account) { $Account } elseif ($env:OP_ACCOUNT) { $env:OP_ACCOUNT.Trim() } else {
        (Read-Host "1Password account (sign-in address or shorthand)").Trim()
    }
    Write-Host "Not signed in, running op signin for $acct..."
    $signinOutput = & op signin --account $acct
    if ($LASTEXITCODE -ne 0) { Stop-Script "op signin failed." }
    Save-Session ($signinOutput -join "`n")
    $OpConfig.Account = $acct
    $r = Invoke-Op -Arguments @("whoami", "--format=json") -What "whoami" -Config $OpConfig
    if (-not $r.Ok) { Stop-Script "Still not signed in: $($r.Err)" }
    return $r.Out | ConvertFrom-Json
}


# Shows who we're running as
function Show-Header {
    param($Me, [string]$Mode)
    $title = "Lock down vaults to view only"
    $line = "─" * ($title.Length + 4)
    Write-Host "`n$Cyan╭$line╮$Reset`n$Cyan│$Reset  $Bold$title$Reset  $Cyan│$Reset`n$Cyan╰$line╯$Reset"
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "Account", ($Me.url -replace '^https://', '').TrimEnd("/"))
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "Signed in", $Me.email)
    Write-Host ("  $Dim{0,-11}$Reset$(if ($Mode -eq 'Live') { $Green } else { $Yellow }){1}$Reset" -f "Mode", $Mode)
}


# Lists the vaults we can manage, trying manage_vault first and allow_managing for Teams accounts
function Get-ManageableVaults {
    $script:ListedWith = "manage_vault"
    $once = @{ Account = $OpConfig.Account; MaxRetries = 0; TimeoutSeconds = $OpConfig.TimeoutSeconds; PermanentErrors = @() }
    $r = Invoke-Op -Arguments @("vault", "list", "--permission=manage_vault", "--format=json") -What "list vaults" -Config $once
    if (-not $r.Ok) {
        Write-Log "manage_vault didn't work as a vault list filter ($($r.Err)), trying allow_managing instead"
        $first = $r.Err
        $r = Invoke-Op -Arguments @("vault", "list", "--permission=allow_managing", "--format=json") -What "list vaults" -Config $once
        if (-not $r.Ok) {
            Stop-Script "Couldn't list the vaults you manage.`n  manage_vault: $first`n  allow_managing: $($r.Err)"
        }
        $script:ListedWith = "allow_managing"
    }
    return @(ConvertFrom-OpJson $r.Out | Where-Object { $_.name.Trim().ToLower() -ne $IgnoredVaultName })
}


# Lowercases a header and drops spaces, underscores and dashes
# Works out whether this is a Business or Teams account: op account get first, then falls back to
# which permission the vault list worked with
function Get-AccountType {
    $r = Invoke-Op -Arguments @("account", "get", "--format=json") -What "account get" -Config $OpConfig
    $type = if ($r.Ok) { "$(($r.Out | ConvertFrom-Json).type)".ToUpper() } else { "" }
    if ($type -eq "BUSINESS") { return @{ Type = "Business"; From = "op account get" } }
    if ($type -in @("TEAM", "TEAMS")) { return @{ Type = "Teams"; From = "op account get" } }
    $why = if ($r.Ok) { "type '$type'" } else { $r.Err }
    Write-Log "op account get didn't say Business or Teams ($why), going by the vault list instead"
    if ($script:ListedWith -eq "allow_managing") { return @{ Type = "Teams"; From = "vault list needed allow_managing" } }
    return @{ Type = "Business"; From = "vault list worked with manage_vault" }
}


function ConvertTo-HeaderKey {
    param([string]$Header)
    return ($Header.ToLower() -replace '[\s_-]', '')
}


# Works out which CSV column is which, ignoring case, spaces and underscores
function Find-Columns {
    param([string[]]$Headers)
    $found = @{}
    foreach ($header in $Headers) {
        $key = ConvertTo-HeaderKey $header
        foreach ($column in $ColumnNames.Keys) {
            if ($key -in $ColumnNames[$column] -and -not $found.ContainsKey($column)) { $found[$column] = $header }
        }
    }
    return $found
}


# Reads the CSV and returns the rows to use, which is every row unless there's an include column
function Read-VaultCsv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { Stop-Script "Can't find $Path. Point -File at your CSV of vaults." }
    $data = @(Import-Csv -Path $Path -Encoding utf8)
    $headerLine = (Get-Content -Path $Path -TotalCount 1 -Encoding utf8) -replace "^\uFEFF", ""
    $headers = if ($headerLine) { @(($headerLine | ConvertFrom-Csv -Header (1..200)).PSObject.Properties.Value | Where-Object { $_ }) } else { @() }
    $columns = Find-Columns -Headers $headers
    if (-not $columns.ContainsKey("vaultName") -and -not $columns.ContainsKey("vaultUUID")) {
        $foundText = if ($headers) { $headers -join ", " } else { "no header row" }
        Stop-Script "$(Split-Path $Path -Leaf) needs a vaultName or vaultUUID column (name, vault, id or uuid work too).`nFound: $foundText"
    }
    $rows = @($data | ForEach-Object {
        $row = $_
        $entry = [ordered]@{}
        foreach ($c in $ColumnNames.Keys) { $entry[$c] = if ($columns.ContainsKey($c)) { "$($row.($columns[$c]))".Trim() } else { "" } }
        [pscustomobject]$entry
    })
    $hasInclude = $columns.ContainsKey("include")
    $picked = @($rows | Where-Object {
        ($_.vaultUUID -or $_.vaultName) -and (-not $hasInclude -or $_.include.ToLower() -in $YesValues)
    })
    $hasAssignments = $columns.ContainsKey("email") -and $columns.ContainsKey("assignment")
    return [pscustomobject]@{ Picked = $picked; Total = $rows.Count; HasInclude = $hasInclude; HasAssignments = $hasAssignments }
}


# Matches each picked row to a live vault by ID, or by name when the ID is blank
function Find-Vaults {
    param($Rows, $Vaults)
    $byId = @{}
    foreach ($v in $Vaults) { $byId[$v.id] = $v }
    $byName = @{}
    foreach ($v in $Vaults) {
        $key = $v.name.ToLower()
        if (-not $byName.ContainsKey($key)) { $byName[$key] = [System.Collections.Generic.List[object]]::new() }
        $byName[$key].Add($v)
    }
    $matched = [ordered]@{}
    $issues = [System.Collections.Generic.List[object]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($r in $Rows) {
        if (-not $seen.Add("$($r.vaultUUID)|$($r.vaultName.ToLower())")) { continue }
        $label = if ($r.vaultName) { $r.vaultName } else { $r.vaultUUID }
        if ($r.vaultUUID) {
            if ($byId.ContainsKey($r.vaultUUID)) { $matched[$r.vaultUUID] = $byId[$r.vaultUUID] }
            else { $issues.Add([pscustomobject]@{ Label = $label; Reason = "no vault with ID $($r.vaultUUID)" }) }
            continue
        }
        $found = if ($byName.ContainsKey($r.vaultName.ToLower())) { @($byName[$r.vaultName.ToLower()]) } else { @() }
        if ($found.Count -eq 1) { $matched[$found[0].id] = $found[0] }
        elseif ($found.Count -gt 1) { $issues.Add([pscustomobject]@{ Label = $label; Reason = "$($found.Count) vaults have this name, add the vaultUUID" }) }
        else { $issues.Add([pscustomobject]@{ Label = $label; Reason = "no vault with this name" }) }
    }
    $vaults = @($matched.Values | Sort-Object { $_.name.ToLower() })
    return [pscustomobject]@{ Vaults = $vaults; Issues = $issues }
}


# Lists the users and groups the CSV says were on each vault, as vault ID plus "user:email" or "group:name"
function Get-CsvAssignments {
    param($Rows, $Vaults)
    $byId = @{}
    $byName = @{}
    foreach ($v in $Vaults) {
        $byId[$v.id] = $v
        $key = $v.name.ToLower()
        $byName[$key] = if ($byName.ContainsKey($key)) { $null } else { $v }   # null when the name isn't unique
    }
    $wanted = [ordered]@{}
    foreach ($r in $Rows) {
        $vault = if ($r.vaultUUID) { $byId[$r.vaultUUID] } else { $byName[$r.vaultName.ToLower()] }
        if (-not $vault) { continue }
        $assignment = "$($r.assignment)".Trim()
        if (-not $assignment) { continue }
        if ($assignment -eq "Direct") {
            if ($r.email) { $wanted["$($vault.id)|user|$($r.email.ToLower())"] = [pscustomobject]@{ Vault = $vault; Type = "user"; Key = $r.email.ToLower() } }
            continue
        }
        $group = if ($r.groupName) { $r.groupName } elseif ($assignment -match '^Group \((.*)\)$') { $Matches[1] } else { "" }
        if (-not $group -or $group.ToLower() -in $IgnoredGroupNames) { continue }
        $wanted["$($vault.id)|group|$($group.ToLower())"] = [pscustomobject]@{ Vault = $vault; Type = "group"; Key = $group.ToLower() }
    }
    return @($wanted.Values)
}


# Adds an entry with no permissions for everyone the CSV lists who isn't on the vault now, so they're granted the view permission
function Add-MissingAssignments {
    param($Wanted, $Entries)
    $result = @{ Added = 0; NotFound = [System.Collections.Generic.List[string]]::new() }
    if (-not $Wanted.Count) { return $result }
    $users = Invoke-Op -Arguments @("user", "list", "--format=json") -What "list users" -Config $OpConfig
    $groups = Invoke-Op -Arguments @("group", "list", "--format=json") -What "list groups" -Config $OpConfig
    Write-Retries $users.Retries
    Write-Retries $groups.Retries
    if (-not $users.Ok -or -not $groups.Ok) { Stop-Script "Couldn't list users and groups: $($users.Err)$($groups.Err)" }
    $index = @{ user = @{}; group = @{} }
    foreach ($u in (ConvertFrom-OpJson $users.Out)) { if ($u.email) { $index.user[$u.email.Trim().ToLower()] = $u } }
    foreach ($g in (ConvertFrom-OpJson $groups.Out)) { $index.group[$g.name.Trim().ToLower()] = $g }

    $present = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($e in $Entries) { [void]$present.Add("$($e.VaultId)|$($e.TargetId)") }
    foreach ($w in $Wanted) {
        $target = $index[$w.Type][$w.Key]
        if (-not $target) {
            $result.NotFound.Add("$($w.Vault.name) / $($w.Type): $($w.Key)")
            Write-Log "not found, can't add back: $($w.Vault.name) / $($w.Type):$($w.Key)"
            continue
        }
        if (-not $present.Add("$($w.Vault.id)|$($target.id)")) { continue }
        $Entries.Add([pscustomobject]@{ VaultId = $w.Vault.id; VaultName = $w.Vault.name; TargetType = $w.Type
                                        TargetId = $target.id; TargetLabel = $(if ($w.Type -eq "user") { $target.email } else { $target.name })
                                        Permissions = @(); AddedBack = $true })
        $result.Added++
    }
    return $result
}


# Reads who's on every vault, users and groups, skipping the groups we leave alone
function Read-Assignments {
    param($Vaults)
    $entries = [System.Collections.Generic.List[object]]::new()
    $failed = 0
    $opDef = ${function:Invoke-Op}.ToString()
    $config = $OpConfig
    Start-Progress "Reading vaults" $Vaults.Count

    $Vaults | ForEach-Object -ThrottleLimit $Threads -Parallel {
        ${function:Invoke-Op} = $using:opDef
        $config = $using:config
        $vault = $_
        $users = Invoke-Op -Arguments @("vault", "user", "list", $vault.id, "--format=json") -What "list users on vault $($vault.id)" -Config $config
        $groups = Invoke-Op -Arguments @("vault", "group", "list", $vault.id, "--format=json") -What "list groups on vault $($vault.id)" -Config $config
        return [pscustomobject]@{ Vault = $vault; Users = $users; Groups = $groups }
    } | ForEach-Object {
        Step-Progress
        $vault = $_.Vault
        Write-Retries $_.Users.Retries
        Write-Retries $_.Groups.Retries
        if ($_.Users.Ok) {
            foreach ($u in (ConvertFrom-OpJson $_.Users.Out)) {
                $entries.Add([pscustomobject]@{ VaultId = $vault.id; VaultName = $vault.name; TargetType = "user"
                                                TargetId = $u.id; TargetLabel = $u.email ?? $u.id; Permissions = @($u.permissions) })
            }
        } else {
            Write-Failure $vault.name "user" "(listing users)" $_.Users.Err
            $failed++
        }
        if ($_.Groups.Ok) {
            foreach ($g in (ConvertFrom-OpJson $_.Groups.Out)) {
                if ("$($g.name)".Trim().ToLower() -in $IgnoredGroupNames) { continue }
                $entries.Add([pscustomobject]@{ VaultId = $vault.id; VaultName = $vault.name; TargetType = "group"
                                                TargetId = $g.id; TargetLabel = $g.name ?? $g.id; Permissions = @($g.permissions) })
            }
        } else {
            Write-Failure $vault.name "group" "(listing groups)" $_.Groups.Err
            $failed++
        }
    }
    Stop-Progress "$($entries.Count) user/group assignment(s)"
    return @{ Entries = $entries; Failed = $failed }
}


# Revokes everything but the view permission first, then grants it to anyone who didn't have it
function Set-ViewOnly {
    param($Entries)
    $results = @{ Changed = 0; Unchanged = 0; Failed = 0 }
    $opDef = ${function:Invoke-Op}.ToString()
    $config = $OpConfig
    $target = $TargetPermission
    $levels = $PermissionLevels
    $teams = $AccountType -eq "Teams"
    $dry = [bool]$DryRun
    Start-Progress "Updating" $Entries.Count

    $Entries | ForEach-Object -ThrottleLimit $Threads -Parallel {
        ${function:Invoke-Op} = $using:opDef
        $config = $using:config
        $e = $_
        $levels = $using:levels
        $current = @($e.Permissions | Where-Object { $_ } | ForEach-Object {
            $p = $_
            if ($using:teams) {
                $level = $levels.Keys | Where-Object { $p -in $levels[$_] } | Select-Object -First 1
                if ($level) { $level } else { $p }
            } elseif ($levels.ContainsKey($p)) { $levels[$p] } else { $p }
        } | Sort-Object -Unique)
        $toRevoke = @($current | Where-Object { $_ -ne $using:target })
        $toGrant = @(if ($using:target -notin $current) { $using:target })
        $result = [pscustomobject]@{ Entry = $e; Grant = $toGrant; Revoke = $toRevoke; Changed = $false; Err = ""
                                     Retries = [System.Collections.Generic.List[object]]::new() }
        if (-not $toGrant.Count -and -not $toRevoke.Count) { return $result }
        $result.Changed = $true
        if ($using:dry) { return $result }

        $kind = $e.TargetType
        foreach ($step in @(@("revoke", $toRevoke), @("grant", $toGrant))) {
            $action, $perms = $step
            if (-not @($perms).Count) { continue }
            $r = Invoke-Op -Arguments @("vault", $kind, $action, "--vault", $e.VaultId, "--$kind", $e.TargetId, "--permissions", (@($perms) -join ",")) `
                           -What "$action on $kind $($e.TargetId) in $($e.VaultName)" -Config $config
            $result.Retries.AddRange($r.Retries)
            if (-not $r.Ok) { $result.Err = $r.Err; return $result }
        }
        return $result
    } | ForEach-Object {
        Step-Progress
        Write-Retries $_.Retries
        $e = $_.Entry
        if ($_.Err) {
            Write-Failure $e.VaultName $e.TargetType $e.TargetLabel $_.Err
            $results.Failed++
            return
        }
        if (-not $_.Changed) { $results.Unchanged++; return }
        $results.Changed++
        $mark = if ($DryRun) { "$Yellow•$Reset" } else { "$Green✓$Reset" }
        $back = if ($e.AddedBack) { "  ${Yellow}(added back from the CSV)$Reset" } else { "" }
        $lines = @("  $mark $Bold$($e.VaultName)$Reset  $Dim$($e.TargetType): $($e.TargetLabel)$Reset$back")
        if ($_.Grant.Count) { $lines += "      $Green{0,-13}$Reset{1}" -f $(if ($DryRun) { "would add" } else { "added" }), ($_.Grant -join ", ") }
        if ($_.Revoke.Count) { $lines += "      $Yellow{0,-13}$Reset{1}" -f $(if ($DryRun) { "would remove" } else { "removed" }), ($_.Revoke -join ", ") }
        Write-Say ($lines -join "`n")
        $what = @()
        if ($_.Grant.Count) { $what += "grant $TargetPermission" }
        if ($_.Revoke.Count) { $what += "revoke $($_.Revoke -join ',')" }
        if ($DryRun) { Write-Log "DRY-RUN: $($e.VaultName) -> $($e.TargetType):$($e.TargetLabel): $($what -join ' and ')" }
        else { Write-Log "locked down $($e.VaultName) -> $($e.TargetType):$($e.TargetLabel) to $TargetPermission only" }
    }
    Stop-Progress ""
    if (-not $results.Changed -and -not $results.Failed) { Write-Host "  ${Dim}Everyone already has $TargetPermission only$Reset" }
    return $results
}


# Runs the whole thing
function Main {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    $me = Connect-Account
    $mode = if ($DryRun) { "Dry run" } else { "Live" }
    Show-Header $me $mode
    Write-Log "Lock down vaults to view only, $mode, signed in as $($me.email) on $($me.url)"

    Write-Heading "Checking"
    $vaults = @(Get-ManageableVaults)
    Write-Host ("  {0,-22} {1}" -f "Vaults found", "$($vaults.Count) $Dim(Employee vault excluded)$Reset")
    $kind = Get-AccountType
    $script:AccountType = $kind.Type
    $script:TargetPermission = $ViewPermissions[$kind.Type]
    Write-Host ("  {0,-22} {1}" -f "Account type", "$($kind.Type) $Dim(locking down to $TargetPermission)$Reset")
    Write-Log "Account type $($kind.Type) (from $($kind.From)), locking down to $TargetPermission"
    if ($File) {
        $csv = Read-VaultCsv -Path $File
        $found = Find-Vaults -Rows $csv.Picked -Vaults $vaults
        $vaults = @($found.Vaults)
        $picked = if ($csv.HasInclude) { "$($csv.Picked.Count) set to include" } else { "$($csv.Picked.Count) with a vault" }
        Write-Host ("  {0,-22} {1}" -f "From CSV", "$($vaults.Count) matched $Dim($($csv.Total) rows, $picked)$Reset")
        Write-Log "Read $($csv.Total) rows from $File, $($csv.Picked.Count) picked, $($vaults.Count) matched"
        foreach ($i in $found.Issues) {
            Write-Log "not matched: $($i.Label): $($i.Reason)"
            Write-Host "  $Yellow!$Reset $($i.Label)  $Dim$($i.Reason), skipped$Reset"
        }
        if (-not $vaults.Count) { Stop-Script "None of the vaults in $(Split-Path $File -Leaf) matched a vault you can manage." }
    }
    $read = Read-Assignments $vaults
    $restore = $null
    if ($File -and $csv.HasAssignments) {
        $restore = Add-MissingAssignments (Get-CsvAssignments $csv.Picked $vaults) $read.Entries
        Write-Host ("  {0,-22} {1}" -f "Not on vault any more", "$($restore.Added) in the CSV $Dim(will be added back with $TargetPermission)$Reset")
        if ($restore.NotFound.Count) {
            Write-Host ("  {0,-22} $Yellow{1}$Reset" -f "Not in this account", "$($restore.NotFound.Count), listed in errors.log")
        }
    }

    Write-Heading $(if ($DryRun) { "Would change" } else { "Changes" })
    $results = Set-ViewOnly $read.Entries
    $failed = $results.Failed + $read.Failed
    $took = ((Get-Date) - $RunStarted).TotalSeconds

    Write-Heading "Summary"
    Write-Host ("  $Green✓$Reset {0,-26}{1,5}" -f $(if ($DryRun) { "Would change" } else { "Changed" }), $results.Changed)
    Write-Host ("  $Dim·$Reset {0,-26}{1,5}" -f "Already $TargetPermission only", $results.Unchanged)
    Write-Host ("  $(if ($failed) { $Red } else { $Dim })✗$Reset {0,-26}{1,5}" -f "Failed", $failed)
    Write-Host ("  ${Dim}Took {0:N1}s$Reset" -f $took)
    Write-Log "Done. $($results.Changed) $(if ($DryRun) { 'would be changed' } else { 'changed' }), $($results.Unchanged) already $TargetPermission only, $failed failed."

    Write-Heading "Logs"
    Write-Host "  $([System.IO.Path]::GetRelativePath((Get-Location).Path, $LogsDir))/"
    Write-Host ("    {0,-24}$Dim{1}$Reset" -f "errors.log", "every change, retry and failure")
    if (Test-Path $FailedPath) { Write-Host ("    {0,-24}$Red{1}$Reset" -f "failed_changes.jsonl", "$failed failure(s)") }
    Write-Host ""
    exit $(if ($failed) { 1 } else { 0 })
}

Main
