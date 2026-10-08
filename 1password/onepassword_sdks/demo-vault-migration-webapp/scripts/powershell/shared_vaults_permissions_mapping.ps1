<#
.SYNOPSIS
    Writes a CSV of who has access to each vault and with which permissions.

.DESCRIPTION
    Looks up who has access to every vault you can manage (or only the vaults listed in -File)
    and writes it to vault_access_report.csv next to this script. Nothing inside the vaults is
    read or copied, only the access. There's one row for each user assigned directly to a vault,
    and one row for each member of each group assigned to a vault, with that assignment's
    permissions.

    The Employee vault is skipped. Vaults are read 10 at a time, and each op command is retried
    up to 3 times. Anything that still can't be read goes in logs\mapping_<timestamp>\errors.log,
    and the script exits with 1 so you know the CSV is missing something.

    The CSV can be fed to recreate_vault_permissions.ps1 (or the Python version) to set the same
    access up in another account.

.PARAMETER File
    Optional. Only checks the vaults listed in this file: a plain text file you write yourself
    with one vault ID per line. This is only read, it isn't where the results go. The results
    are always written to vault_access_report.csv. Leave it out to check every vault you can
    manage.

.PARAMETER Account
    The 1Password account to use (sign-in address or shorthand), if you're signed in to more
    than one.

.EXAMPLE
    ./shared_vaults_permissions_mapping.ps1

    Writes the access for every vault you can manage to vault_access_report.csv.

.EXAMPLE
    ./shared_vaults_permissions_mapping.ps1 -File vault-ids.txt -Account mycompany

    Writes the access for only the vaults whose IDs are listed in vault-ids.txt, in the
    mycompany account, to vault_access_report.csv.

.NOTES
    Requires PowerShell 7 or later and the 1Password CLI v2.25 or later, signed in.
    The CSV has names and email addresses in it, so keep it out of source control.
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$File,
    [string]$Account
)

$ErrorActionPreference = "Stop"
$Threads = 10
$ExcludedVaults = @("Employee")
$OutputPath = Join-Path $PSScriptRoot "vault_access_report.csv"

$OpConfig = @{
    Account         = $Account
    MaxRetries      = 3
    TimeoutSeconds  = 30
    PermanentErrors = @("does not have access", "not found", "isn't a vault", "isn't a group",
                        "not authorized", "no accounts for filter")
}

$IsTty = -not [Console]::IsOutputRedirected
$UseColor = $IsTty -and -not $env:NO_COLOR
$Bold, $Dim, $Red, $Green, $Yellow, $Cyan, $Reset = if ($UseColor) {
    "`e[1m", "`e[2m", "`e[91m", "`e[92m", "`e[93m", "`e[96m", "`e[0m"
} else { "", "", "", "", "", "", "" }

$RunStarted = Get-Date
$LogsDir = Join-Path $PSScriptRoot "logs" "mapping_$($RunStarted.ToString('yyyy-MM-dd_HH-mm-ss'))"
$ErrorsPath = Join-Path $LogsDir "errors.log"
$script:Progress = @{ Label = ""; Done = 0; Total = 0; Started = $null }
$script:ErrorCount = 0


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
        $retries.Add([pscustomobject]@{ Status = "RETRY $($attempt + 1)/$($Config.MaxRetries)"; What = $What; Err = $err })
        Start-Sleep -Seconds ([math]::Pow(2, $attempt))
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


# Draws the progress bar with a time estimate, only when running in a terminal
function Show-Progress {
    if (-not $IsTty -or -not $script:Progress.Total) { return }
    $done, $total = $script:Progress.Done, $script:Progress.Total
    $width = 24
    $filled = [int][math]::Floor($width * $done / $total)
    $bar = ("█" * $filled) + ("░" * ($width - $filled))
    $eta = ""
    if ($done -gt 0 -and $done -lt $total) {
        $elapsed = ((Get-Date) - $script:Progress.Started).TotalSeconds
        $eta = "  ${Dim}about {0:N0}s left$Reset" -f ($elapsed / $done * ($total - $done))
    }
    Write-Host ("`r  {0,-22} $Cyan{1}$Reset {2}/{3}{4}`e[K" -f $script:Progress.Label, $bar, $done, $total, $eta) -NoNewline
}


# Starts a new progress bar
function Start-Progress {
    param([string]$Label, [int]$Total)
    $script:Progress = @{ Label = $Label; Done = 0; Total = $Total; Started = Get-Date }
    Show-Progress
}


# Moves the progress bar forward by one
function Step-Progress {
    $script:Progress.Done++
    Show-Progress
}


# Clears the progress bar and leaves a finished line in its place
function Stop-Progress {
    param([string]$Result)
    if ($IsTty -and $script:Progress.Total) { Write-Host "`r`e[K" -NoNewline }
    Write-Host ("  {0,-22} {1}" -f $script:Progress.Label, $Result)
    $script:Progress.Total = 0
}


# Prints a section heading
function Write-Heading {
    param([string]$Title)
    Write-Host "`n$Bold$Title$Reset"
}


# Prints a label and value lined up with the rest of the section
function Write-Field {
    param([string]$Label, $Value)
    Write-Host ("  {0,-22} {1}" -f $Label, $Value)
}


# Writes a timestamped entry to the error log
function Write-ErrorLog {
    param([string]$Status, [string]$Subject, [string]$Detail)
    if ($Status -eq "FAILED") { $script:ErrorCount++ }
    $lines = @(("{0}  {1,-12} {2}" -f (Get-Date -Format "HH:mm:ss"), $Status, $Subject), ((" " * 24) + $Detail))
    Add-Content -Path $ErrorsPath -Value $lines -Encoding utf8
}


# Records the retries an op command needed
function Write-Retries {
    param($Retries)
    foreach ($r in $Retries) { Write-ErrorLog $r.Status $r.What $r.Err }
}


# Writes permissions the same way the Python version does, so either recreate script can read them
function Format-Permissions {
    param($Permissions)
    return "[" + ((@($Permissions) | Where-Object { $_ } | ForEach-Object { "'$_'" }) -join ", ") + "]"
}


# Stops early unless the CLI is at least version 2.25
function Assert-CliVersion {
    $r = Invoke-Op -Arguments @("--version") -What "check the CLI version" -Config $OpConfig
    if (-not $r.Ok) { Stop-Script "Couldn't check the 1Password CLI version: $($r.Err)" }
    $major, $minor = $r.Out.Trim().Split(".")[0..1] | ForEach-Object { [int]$_ }
    if ($major -ne 2 -or $minor -lt 25) {
        Stop-Script "Requires 1Password CLI v2.25 or higher. See https://developer.1password.com/docs/cli/get-started."
    }
    return $r.Out.Trim()
}


# Shows who we're running as and stops if the CLI isn't signed in
function Show-Header {
    param([string]$CliVersion)
    $r = Invoke-Op -Arguments @("whoami", "--format=json") -What "whoami" -Config $OpConfig
    if (-not $r.Ok) { Stop-Script "Not signed in to 1Password ($($r.Err)). Run op signin first." }
    $me = $r.Out | ConvertFrom-Json
    $title = "Vault permissions mapping"
    $line = "─" * ($title.Length + 4)
    Write-Host "`n$Cyan╭$line╮$Reset`n$Cyan│$Reset  $Bold$title$Reset  $Cyan│$Reset`n$Cyan╰$line╯$Reset"
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "Account", ($me.url -replace '^https://', '').TrimEnd("/"))
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "Signed in", $me.email)
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "CLI", $CliVersion)
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "Vaults", $(if ($File) { "listed in $File" } else { "every vault you can manage" }))
    return $me
}


# Gets the vaults to report on, either every vault we can manage or the IDs listed in -File
function Get-Vaults {
    if (-not $File) {
        $r = Invoke-Op -Arguments @("vault", "list", "--permission=manage_vault", "--format=json") -What "list vaults" -Config $OpConfig
        Write-Retries $r.Retries
        if (-not $r.Ok) { Stop-Script "Couldn't list vaults: $($r.Err)" }
        return @(ConvertFrom-OpJson $r.Out | Where-Object { $_.name -notin $ExcludedVaults })
    }

    if (-not (Test-Path $File)) { Stop-Script "Can't find $File." }
    $ids = @(Get-Content -Path $File | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $vaults = [System.Collections.Generic.List[object]]::new()
    foreach ($id in $ids) {
        $r = Invoke-Op -Arguments @("vault", "get", $id, "--format=json") -What "get vault $id" -Config $OpConfig
        Write-Retries $r.Retries
        if (-not $r.Ok) { Stop-Script "Couldn't load vault $id`: $($r.Err)" }
        $vault = $r.Out | ConvertFrom-Json
        if ($vault.name -notin $ExcludedVaults) { $vaults.Add($vault) }
    }
    return $vaults
}


# Reads the direct users and groups on every vault, 10 at a time
function Read-VaultAccess {
    param($Vaults)
    $access = @{}
    $opDef = ${function:Invoke-Op}.ToString()
    $config = $OpConfig
    Start-Progress "Reading vaults" $Vaults.Count

    $Vaults | ForEach-Object -ThrottleLimit $Threads -Parallel {
        ${function:Invoke-Op} = $using:opDef
        $config = $using:config
        $vault = $_
        $users = Invoke-Op -Arguments @("vault", "user", "list", $vault.id, "--format=json") -What "list users on $($vault.name)" -Config $config
        $groups = Invoke-Op -Arguments @("vault", "group", "list", $vault.id, "--format=json") -What "list groups on $($vault.name)" -Config $config
        return [pscustomobject]@{ Vault = $vault; Users = $users; Groups = $groups }
    } | ForEach-Object {
        Step-Progress
        $entry = @{ Users = @(); Groups = @() }
        foreach ($part in @("Users", "Groups")) {
            $r = $_.$part
            Write-Retries $r.Retries
            if ($r.Ok) { $entry[$part] = @(ConvertFrom-OpJson $r.Out) }
            else { Write-ErrorLog "FAILED" "list $($part.ToLower()) on $($_.Vault.name)" $r.Err }
        }
        $access[$_.Vault.id] = $entry
    }
    Stop-Progress "$($Vaults.Count) vaults"
    return $access
}


# Reads the members of every group that's on at least one vault, 10 at a time
function Read-GroupMembers {
    param([hashtable]$Access)
    $groups = @{}
    foreach ($entry in $Access.Values) { foreach ($g in $entry.Groups) { $groups[$g.id] = $g.name } }
    $members = @{}
    if (-not $groups.Count) { return $members }
    $opDef = ${function:Invoke-Op}.ToString()
    $config = $OpConfig
    Start-Progress "Reading groups" $groups.Count

    $groups.GetEnumerator() | ForEach-Object -ThrottleLimit $Threads -Parallel {
        ${function:Invoke-Op} = $using:opDef
        $group = $_
        $r = Invoke-Op -Arguments @("group", "user", "list", $group.Key, "--format=json") -What "list members of $($group.Value)" -Config $using:config
        return [pscustomobject]@{ Id = $group.Key; Name = $group.Value; Result = $r }
    } | ForEach-Object {
        Step-Progress
        Write-Retries $_.Result.Retries
        if ($_.Result.Ok) { $members[$_.Id] = @(ConvertFrom-OpJson $_.Result.Out) }
        else { $members[$_.Id] = @(); Write-ErrorLog "FAILED" "list members of $($_.Name)" $_.Result.Err }
    }
    Stop-Progress "$($groups.Count) groups"
    return $members
}


# Writes the CSV, one row per direct user and one per member of each group on each vault
function Write-Report {
    param($Vaults, [hashtable]$Access, [hashtable]$Members)
    $rows = foreach ($vault in $Vaults) {
        $entry = $Access[$vault.id]
        foreach ($user in $entry.Users) {
            [pscustomobject][ordered]@{
                vaultName = $vault.name; vaultUUID = $vault.id; userName = $user.name; groupName = ""
                email = $user.email; userUUID = $user.id; assignment = "Direct"; status = $user.state
                permissions = Format-Permissions $user.permissions
            }
        }
        foreach ($group in $entry.Groups) {
            foreach ($member in $Members[$group.id]) {
                [pscustomobject][ordered]@{
                    vaultName = $vault.name; vaultUUID = $vault.id; userName = $member.name; groupName = $group.name
                    email = $member.email; userUUID = $member.id; assignment = "Group ($($group.name))"; status = $member.state
                    permissions = Format-Permissions $group.permissions
                }
            }
        }
    }
    $rows = @($rows)
    if ($rows.Count) {
        $rows | Export-Csv -Path $OutputPath -NoTypeInformation -UseQuotes AsNeeded -Encoding utf8
    } else {
        Set-Content -Path $OutputPath -Encoding utf8 -Value "vaultName,vaultUUID,userName,groupName,email,userUUID,assignment,status,permissions"
    }
    return $rows
}


# Runs the whole thing
function Main {
    $version = Assert-CliVersion
    $me = Show-Header $version
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    Set-Content -Path $ErrorsPath -Encoding utf8 -Value @(
        "Vault permissions mapping",
        "Started    $($RunStarted.ToString('yyyy-MM-dd HH:mm:ss'))",
        "Signed in  $($me.email)",
        "Account    $($me.url)",
        "")

    Write-Heading "Reading"
    $vaults = @(Get-Vaults)
    if (-not $vaults.Count) { Write-Host "  ${Dim}No vaults to process$Reset`n"; return }
    Write-Field "Vaults found" $vaults.Count
    $access = Read-VaultAccess $vaults
    $members = Read-GroupMembers $access

    $rows = Write-Report $vaults $access $members
    $direct = @($rows | Where-Object { $_.assignment -eq "Direct" }).Count
    $took = ((Get-Date) - $RunStarted).TotalSeconds
    Add-Content -Path $ErrorsPath -Encoding utf8 -Value @("",
        $(if ($script:ErrorCount) { "Finished   $($script:ErrorCount) failed" } else { "No errors." }))

    Write-Heading "Summary"
    Write-Host ("  $Green✓$Reset {0,-26}{1,5}" -f "Vaults", $vaults.Count)
    Write-Host ("  $Green✓$Reset {0,-26}{1,5}" -f "Direct assignments", $direct)
    Write-Host ("  $Green✓$Reset {0,-26}{1,5}" -f "Group member rows", ($rows.Count - $direct))
    Write-Host ("  $(if ($script:ErrorCount) { $Red } else { $Dim })✗$Reset {0,-26}{1,5}" -f "Couldn't read", $script:ErrorCount)
    Write-Host ("  ${Dim}Took {0:N1}s$Reset" -f $took)

    Write-Heading "Output"
    Write-Host "  $([System.IO.Path]::GetRelativePath((Get-Location).Path, $OutputPath))"
    $errorsShown = [System.IO.Path]::GetRelativePath((Get-Location).Path, $ErrorsPath)
    Write-Host ("  $(if ($script:ErrorCount) { $Red } else { $Dim }){0}  {1}$Reset" -f $errorsShown,
        $(if ($script:ErrorCount) { "$($script:ErrorCount) error(s)" } else { "no errors" }))
    if ($script:ErrorCount) {
        Write-Host "`n  ${Yellow}Some vaults or groups couldn't be read, so the CSV is missing their access.$Reset"
    }
    Write-Host ""
    exit $(if ($script:ErrorCount) { 1 } else { 0 })
}

Main
