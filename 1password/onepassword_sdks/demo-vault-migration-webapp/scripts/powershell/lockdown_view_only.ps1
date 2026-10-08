<#
.SYNOPSIS
    Brings every user and group on your vaults down to view only.

.DESCRIPTION
    Checks every vault you can manage. Anyone assigned directly, and any group assigned, ends up
    with allow_viewing and nothing else. allow_viewing is granted first, then everything else is
    revoked, so nobody loses access in between.

    Left alone on purpose: the Recovery, Administrators, Owners, Provision Managers and Security
    groups, since changing them would get in the way of running the account, and the Employee
    vault.

    It's safe to run more than once. Current permissions are checked first, and anyone already
    view only is left as is. Work runs 5 at a time and each op command gets up to 5 tries.

    Every change, retry and failure goes in logs\<timestamp>\errors.log, and failures also go in
    failed_changes.jsonl.

.PARAMETER Account
    The 1Password account to sign in to, only used if the CLI isn't already signed in.
    Falls back to the OP_ACCOUNT environment variable, then asks.

.PARAMETER DryRun
    Show what would change without granting or revoking anything.

.EXAMPLE
    ./lockdown_view_only.ps1 -DryRun

    Shows who would be changed.

.EXAMPLE
    ./lockdown_view_only.ps1 -Account mycompany

    Locks down the mycompany account's vaults.

.NOTES
    Written for 1Password Teams, which has three permission levels: allow_viewing,
    allow_editing and allow_managing.
    Requires PowerShell 7 or later and the 1Password CLI.
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Account,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Threads = 5
$TargetPermission = "allow_viewing"
$IgnoredVaultName = "employee"
$IgnoredGroupNames = @("recovery", "administrators", "owners", "provision managers", "security")

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
    return @($Text | ConvertFrom-Json)
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


# Reuses the CLI's session if it's signed in, otherwise signs in and passes --account from then on
function Connect-Account {
    $r = Invoke-Op -Arguments @("whoami", "--format=json") -What "whoami" -Config @{ MaxRetries = 0; TimeoutSeconds = 15; PermanentErrors = @() }
    if ($r.Ok) { return $r.Out | ConvertFrom-Json }

    $acct = if ($Account) { $Account } elseif ($env:OP_ACCOUNT) { $env:OP_ACCOUNT.Trim() } else {
        (Read-Host "1Password account (sign-in address or shorthand)").Trim()
    }
    Write-Host "Not signed in, running op signin for $acct..."
    & op signin --account $acct
    if ($LASTEXITCODE -ne 0) { Stop-Script "op signin failed." }
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
    $once = @{ Account = $OpConfig.Account; MaxRetries = 0; TimeoutSeconds = $OpConfig.TimeoutSeconds; PermanentErrors = @() }
    $r = Invoke-Op -Arguments @("vault", "list", "--permission=manage_vault", "--format=json") -What "list vaults" -Config $once
    if (-not $r.Ok) {
        Write-Log "manage_vault didn't work as a vault list filter ($($r.Err)), trying allow_managing instead"
        $first = $r.Err
        $r = Invoke-Op -Arguments @("vault", "list", "--permission=allow_managing", "--format=json") -What "list vaults" -Config $once
        if (-not $r.Ok) {
            Stop-Script "Couldn't list the vaults you manage.`n  manage_vault: $first`n  allow_managing: $($r.Err)"
        }
    }
    return @(ConvertFrom-OpJson $r.Out | Where-Object { $_.name.Trim().ToLower() -ne $IgnoredVaultName })
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


# Grants allow_viewing first so nobody loses access for a moment, then revokes everything else
function Set-ViewOnly {
    param($Entries)
    $results = @{ Changed = 0; Unchanged = 0; Failed = 0 }
    $opDef = ${function:Invoke-Op}.ToString()
    $config = $OpConfig
    $target = $TargetPermission
    $dry = [bool]$DryRun
    Start-Progress "Updating" $Entries.Count

    $Entries | ForEach-Object -ThrottleLimit $Threads -Parallel {
        ${function:Invoke-Op} = $using:opDef
        $config = $using:config
        $e = $_
        $toRevoke = @($e.Permissions | Where-Object { $_ -and $_ -ne $using:target } | Sort-Object)
        $toGrant = @(if ($using:target -notin $e.Permissions) { $using:target })
        $result = [pscustomobject]@{ Entry = $e; Grant = $toGrant; Revoke = $toRevoke; Changed = $false; Err = ""
                                     Retries = [System.Collections.Generic.List[object]]::new() }
        if (-not $toGrant.Count -and -not $toRevoke.Count) { return $result }
        $result.Changed = $true
        if ($using:dry) { return $result }

        $kind = $e.TargetType
        foreach ($step in @(@("grant", $toGrant), @("revoke", $toRevoke))) {
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
        $lines = @("  $mark $Bold$($e.VaultName)$Reset  $Dim$($e.TargetType): $($e.TargetLabel)$Reset")
        if ($_.Grant.Count) { $lines += "      $Green{0,-13}$Reset{1}" -f $(if ($DryRun) { "would add" } else { "added" }), ($_.Grant -join ", ") }
        if ($_.Revoke.Count) { $lines += "      $Yellow{0,-13}$Reset{1}" -f $(if ($DryRun) { "would remove" } else { "removed" }), ($_.Revoke -join ", ") }
        Write-Say ($lines -join "`n")
        $what = @()
        if ($_.Grant.Count) { $what += "grant allow_viewing" }
        if ($_.Revoke.Count) { $what += "revoke $($_.Revoke -join ',')" }
        if ($DryRun) { Write-Log "DRY-RUN: $($e.VaultName) -> $($e.TargetType):$($e.TargetLabel): $($what -join ' and ')" }
        else { Write-Log "locked down $($e.VaultName) -> $($e.TargetType):$($e.TargetLabel) to view only" }
    }
    Stop-Progress ""
    if (-not $results.Changed -and -not $results.Failed) { Write-Host "  ${Dim}Everyone's already view only$Reset" }
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
    $read = Read-Assignments $vaults

    Write-Heading $(if ($DryRun) { "Would change" } else { "Changes" })
    $results = Set-ViewOnly $read.Entries
    $failed = $results.Failed + $read.Failed
    $took = ((Get-Date) - $RunStarted).TotalSeconds

    Write-Heading "Summary"
    Write-Host ("  $Green✓$Reset {0,-26}{1,5}" -f $(if ($DryRun) { "Would change" } else { "Changed" }), $results.Changed)
    Write-Host ("  $Dim·$Reset {0,-26}{1,5}" -f "Already view only", $results.Unchanged)
    Write-Host ("  $(if ($failed) { $Red } else { $Dim })✗$Reset {0,-26}{1,5}" -f "Failed", $failed)
    Write-Host ("  ${Dim}Took {0:N1}s$Reset" -f $took)
    Write-Log "Done. $($results.Changed) $(if ($DryRun) { 'would be changed' } else { 'changed' }), $($results.Unchanged) already view-only, $failed failed."

    Write-Heading "Logs"
    Write-Host "  $([System.IO.Path]::GetRelativePath((Get-Location).Path, $LogsDir))/"
    Write-Host ("    {0,-24}$Dim{1}$Reset" -f "errors.log", "every change, retry and failure")
    if (Test-Path $FailedPath) { Write-Host ("    {0,-24}$Red{1}$Reset" -f "failed_changes.jsonl", "$failed failure(s)") }
    Write-Host ""
    exit $(if ($failed) { 1 } else { 0 })
}

Main
