<#
.SYNOPSIS
    Recreates vault access from the CSV made by shared_vaults_permissions_mapping.ps1.

.DESCRIPTION
    Reads vault_access_report.csv and grants the same users and groups the same permissions on
    the matching vaults in the account you're signed in to. Use it after migrating vaults to a
    new account.

    Matching is by name, never by ID: vaults by name, groups by name and users by email.
    A "(Migrated)" on the end of a vault name is ignored, so Finance matches Finance (Migrated).
    If both exist, the (Migrated) one is used.

    Groups that don't exist can be created, along with their members, with -CreateGroups.
    Recovery, Team Members, Administrators, Provision Managers, Security and Owners are never
    created. The Recovery group's access is always skipped since 1Password manages it.

    Permissions are only added, never removed. Work runs 10 at a time and each op command is
    retried up to 3 times.

    Everything that couldn't be done (missing vaults, users or groups, and failures) is
    summed up on screen and listed in full in logs\recreate_<timestamp>\not_recreated.csv.
    Every change is written to audit.log in the same folder.

.PARAMETER File
    The CSV to read. Defaults to vault_access_report.csv next to this script.

.PARAMETER Account
    The 1Password account to use (sign-in address or shorthand), if you're signed in to more
    than one.

.PARAMETER CreateGroups
    Create missing groups and add their members without asking.

.PARAMETER NoCreateGroups
    Never create groups, and don't ask. Without either switch, you're asked when groups are
    missing.

.PARAMETER DryRun
    Show what would happen without changing anything.

.EXAMPLE
    ./recreate_vault_permissions.ps1 -DryRun

    Shows what would be recreated from vault_access_report.csv.

.EXAMPLE
    ./recreate_vault_permissions.ps1 -File ./access.csv -CreateGroups

    Recreates the access listed in access.csv, creating any missing groups first.

.NOTES
    Requires PowerShell 7 or later and the 1Password CLI, signed in as someone who can manage
    the vaults, groups and users involved.
    A group with no members has no rows in the CSV, so its vault access can't be recreated.
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$File = (Join-Path $PSScriptRoot "vault_access_report.csv"),
    [string]$Account,
    [switch]$CreateGroups,
    [switch]$NoCreateGroups,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Threads = 10
$NamesShown = 3
$MigratedSuffix = "(Migrated)"
$BuiltInGroups = @("recovery", "team members", "administrators", "provision managers", "security", "owners")
$SkippedGroups = @("recovery")
$RequiredColumns = @("vaultName", "userName", "groupName", "email", "assignment", "permissions")

$OpConfig = @{
    Account         = $Account
    MaxRetries      = 3
    TimeoutSeconds  = 30
    PermanentErrors = @("does not have access", "not found", "isn't a vault", "isn't a group", "isn't a user",
                        "not authorized", "no accounts for filter", "already exists")
}

$IsTty = -not [Console]::IsOutputRedirected
$UseColor = $IsTty -and -not $env:NO_COLOR
$Bold, $Dim, $Red, $Green, $Yellow, $Cyan, $Reset = if ($UseColor) {
    "`e[1m", "`e[2m", "`e[91m", "`e[92m", "`e[93m", "`e[96m", "`e[0m"
} else { "", "", "", "", "", "", "" }

$RunStarted = Get-Date
$LogsDir = Join-Path $PSScriptRoot "logs" "recreate_$($RunStarted.ToString('yyyy-MM-dd_HH-mm-ss'))"
$AuditPath = Join-Path $LogsDir "audit.log"
$ReportPath = Join-Path $LogsDir "not_recreated.csv"
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


# Clears the progress bar and leaves a finished line in its place
function Stop-Progress {
    param([string]$Result)
    if ($IsTty -and $script:Progress.Total) { Write-Host "`r`e[K" -NoNewline }
    Write-Host ("  {0,-22} {1}" -f $script:Progress.Label, $Result)
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


# Prints a label and value lined up with the rest of the section
function Write-Field {
    param([string]$Label, $Value)
    Write-Host ("  {0,-22} {1}" -f $Label, $Value)
}


# Writes a timestamped entry to the audit log
function Write-Audit {
    param([string]$Status, [string]$Subject, [string[]]$Details = @())
    $lines = @("{0}  {1,-12} {2}" -f (Get-Date -Format "HH:mm:ss"), $Status, $Subject)
    $lines += $Details | ForEach-Object { (" " * 24) + $_ }
    Add-Content -Path $AuditPath -Value $lines -Encoding utf8
}


# Records the retries an op command needed
function Write-Retries {
    param($Retries)
    foreach ($r in $Retries) { Write-Audit $r.Status $r.What @($r.Err) }
}


# Turns the permissions column, written as a Python list, back into a list
function ConvertFrom-PermissionText {
    param([string]$Text)
    $parts = "$Text".Trim().Trim("[", "]") -split "," |
        ForEach-Object { $_.Trim().Trim("'", '"').Trim() } |
        Where-Object { $_ }
    return @($parts | Sort-Object -Unique)
}


# Drops "(Migrated)" from the end of a vault name so source and destination names line up
function Get-BaseName {
    param([string]$Name)
    $name = $Name.Trim()
    if ($name.EndsWith($MigratedSuffix, [StringComparison]::OrdinalIgnoreCase)) {
        $name = $name.Substring(0, $name.Length - $MigratedSuffix.Length)
    }
    return $name.Trim().ToLower()
}


# Reads the mapping CSV into vault assignments and group memberships, ignoring every UUID in it
function Read-SourceCsv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { Stop-Script "Can't find $Path. Point to it with -File." }
    $header = (Get-Content -Path $Path -TotalCount 1) -split "," | ForEach-Object { $_.Trim().Trim('"') }
    $missing = $RequiredColumns | Where-Object { $_ -notin $header }
    if ($missing) { Stop-Script "$(Split-Path $Path -Leaf) is missing columns: $($missing -join ', ')" }

    $vaults = @{}
    $members = @{}
    $rows = @(Import-Csv -Path $Path)
    foreach ($row in $rows) {
        $vaultName = $row.vaultName.Trim()
        $email = "$($row.email)".Trim().ToLower()
        $perms = ConvertFrom-PermissionText $row.permissions
        if (-not $vaults.ContainsKey($vaultName)) { $vaults[$vaultName] = @{ Users = @{}; Groups = @{} } }
        $vault = $vaults[$vaultName]
        if ($row.assignment.Trim() -eq "Direct") {
            $vault.Users[$email] = $perms
            continue
        }
        $group = if ($row.groupName) { $row.groupName.Trim() } else { $row.assignment.Trim() -replace '^Group \((.*)\)$', '$1' }
        $vault.Groups[$group] = $perms
        if ($email) {
            if (-not $members.ContainsKey($group)) { $members[$group] = [System.Collections.Generic.HashSet[string]]::new() }
            [void]$members[$group].Add($email)
        }
    }
    return @{ Vaults = $vaults; Members = $members; Rows = $rows.Count }
}


# Runs an op command that has to work, and stops the script if it doesn't
function Invoke-OpRequired {
    param([string[]]$Arguments, [string]$What)
    $result = Invoke-Op -Arguments $Arguments -What $What -Config $OpConfig
    Write-Retries $result.Retries
    if (-not $result.Ok) { Write-Host ""; Stop-Script "Couldn't $What`: $($result.Err)" }
    return ConvertFrom-OpJson $result.Out
}


# Reads the vaults, users and groups that exist in the destination account
function Read-Destination {
    Start-Progress "Reading destination" 3
    $vaults = Invoke-OpRequired @("vault", "list", "--permission", "manage_vault", "--format=json") "list vaults"
    Step-Progress
    $users = Invoke-OpRequired @("user", "list", "--format=json") "list users"
    Step-Progress
    $groups = Invoke-OpRequired @("group", "list", "--format=json") "list groups"
    Step-Progress
    Stop-Progress "$($vaults.Count) vaults, $($users.Count) users, $($groups.Count) groups"

    $vaultIndex = @{}
    foreach ($v in $vaults) {
        $key = Get-BaseName $v.name
        if (-not $vaultIndex.ContainsKey($key)) { $vaultIndex[$key] = [System.Collections.Generic.List[object]]::new() }
        $vaultIndex[$key].Add($v)
    }
    $userIndex = @{}
    foreach ($u in $users) { if ($u.email) { $userIndex[$u.email.Trim().ToLower()] = $u } }
    $groupIndex = @{}
    foreach ($g in $groups) { $groupIndex[$g.name.Trim().ToLower()] = $g }
    return @{ Vaults = $vaultIndex; Users = $userIndex; Groups = $groupIndex }
}


# Finds the destination vault for a source vault name, preferring the "(Migrated)" copy if there are both
function Find-Vault {
    param([string]$Name, [hashtable]$VaultIndex)
    $candidates = @($VaultIndex[(Get-BaseName $Name)] | Where-Object { $_ })
    if ($candidates.Count -gt 1) {
        $migrated = @($candidates | Where-Object { $_.name.Trim().EndsWith($MigratedSuffix, [StringComparison]::OrdinalIgnoreCase) })
        if ($migrated.Count) { $candidates = $migrated }
    }
    if (-not $candidates.Count) { return @{ Vault = $null; Reason = "vault not found" } }
    if ($candidates.Count -gt 1) { return @{ Vault = $null; Reason = "$($candidates.Count) vaults have this name" } }
    return @{ Vault = $candidates[0]; Reason = "" }
}


# Builds one row for the report of things that couldn't be recreated
function New-Issue {
    param([string]$Category, [string]$Vault, [string]$Type, [string]$Name, [string[]]$Perms, [string]$Reason)
    return [pscustomobject]@{
        category = $Category; vault = $Vault; type = $Type; name = $Name
        permissions = ($Perms -join ", "); reason = $Reason
    }
}


# Builds one grant to make
function New-Task {
    param([string]$Kind, $Vault, [string]$Name, $Id, [string[]]$Perms)
    return [pscustomobject]@{ Kind = $Kind; VaultId = $Vault.id; VaultName = $Vault.name; Name = $Name; Id = $Id; Perms = $Perms }
}


# Works out every grant to make, every group to create, and everything that can't be done
function Get-Plan {
    param([hashtable]$Source, [hashtable]$Destination, [bool]$Create)
    $tasks = [System.Collections.Generic.List[object]]::new()
    $issues = [System.Collections.Generic.List[object]]::new()
    $toCreate = [System.Collections.Generic.SortedSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

    foreach ($vaultName in ($Source.Vaults.Keys | Sort-Object)) {
        $assigned = $Source.Vaults[$vaultName]
        $match = Find-Vault $vaultName $Destination.Vaults
        if (-not $match.Vault) {
            foreach ($u in $assigned.Users.GetEnumerator()) { $issues.Add((New-Issue "vault" $vaultName "user" $u.Key $u.Value $match.Reason)) }
            foreach ($g in $assigned.Groups.GetEnumerator()) { $issues.Add((New-Issue "vault" $vaultName "group" $g.Key $g.Value $match.Reason)) }
            continue
        }

        foreach ($u in $assigned.Users.GetEnumerator()) {
            $user = $Destination.Users[$u.Key]
            if (-not $user) { $issues.Add((New-Issue "user" $vaultName "user" $u.Key $u.Value "user not found")); continue }
            $tasks.Add((New-Task "user" $match.Vault $u.Key $user.id $u.Value))
        }

        foreach ($g in $assigned.Groups.GetEnumerator()) {
            $key = $g.Key.ToLower()
            if ($key -in $SkippedGroups) {
                $issues.Add((New-Issue "skipped" $vaultName "group" $g.Key $g.Value "managed by 1Password, skipped"))
            } elseif ($Destination.Groups.ContainsKey($key)) {
                $tasks.Add((New-Task "group" $match.Vault $g.Key $Destination.Groups[$key].id $g.Value))
            } elseif ($key -in $BuiltInGroups -or -not $Create) {
                $issues.Add((New-Issue "group" $vaultName "group" $g.Key $g.Value "group not found"))
            } else {
                [void]$toCreate.Add($g.Key)
                $tasks.Add((New-Task "group" $match.Vault $g.Key $null $g.Value))
            }
        }
    }

    foreach ($group in $toCreate) {
        foreach ($email in ($Source.Members[$group] | Sort-Object)) {
            if (-not $Destination.Users.ContainsKey($email)) {
                $issues.Add((New-Issue "user" "" "group member" $email @() "user not found, not added to $group"))
            }
        }
    }
    return @{ Tasks = $tasks; Issues = $issues; ToCreate = @($toCreate) }
}


# Lists the groups that are missing here but could be created
function Get-CreatableGroups {
    param([hashtable]$Source, [hashtable]$GroupIndex)
    $names = $Source.Vaults.Values | ForEach-Object { $_.Groups.Keys } | Sort-Object -Unique
    return @($names | Where-Object { -not $GroupIndex.ContainsKey($_.ToLower()) -and $_.ToLower() -notin $BuiltInGroups })
}


# Joins a few names for the screen and says how many more there are
function Format-Names {
    param([string[]]$Names, [int]$Limit = $NamesShown)
    $shown = ($Names | Select-Object -First $Limit) -join ", "
    if ($Names.Count -gt $Limit) { $shown += " +$($Names.Count - $Limit) more" }
    return $shown
}


# Asks whether to create missing groups, when -CreateGroups wasn't given and someone's at the keyboard
function Request-CreateGroups {
    param([string[]]$Missing)
    if (-not $Missing.Count -or [Console]::IsInputRedirected) { return $false }
    Write-Heading "$($Missing.Count) group(s) don't exist in this account"
    Write-Host "  $Dim$(Format-Names $Missing 8)$Reset"
    $answer = Read-Host "  Create them and add their members? [y/N]"
    return $answer.Trim().ToLower() -in @("y", "yes")
}


# Creates the missing groups on 10 threads, adds the members they had, and returns their new IDs
function New-Groups {
    param([string[]]$Groups, [hashtable]$Source, [hashtable]$Destination, $Issues)
    Write-Heading $(if ($DryRun) { "Would create groups" } else { "Creating groups" })
    $created = @{}
    $opDef = ${function:Invoke-Op}.ToString()
    $members = $Source.Members
    $userIndex = $Destination.Users
    $config = $OpConfig
    $dry = [bool]$DryRun

    $Groups | ForEach-Object -ThrottleLimit $Threads -Parallel {
        ${function:Invoke-Op} = $using:opDef
        $config = $using:config
        $group = $_
        $emails = @(($using:members)[$group] | Sort-Object)
        $users = $using:userIndex
        $found = @($emails | Where-Object { $users.ContainsKey($_) })
        $result = [pscustomobject]@{ Group = $group; Id = $null; Added = 0; Total = $emails.Count; Err = ""
                                     Retries = [System.Collections.Generic.List[object]]::new()
                                     Log = [System.Collections.Generic.List[object]]::new() }
        if ($using:dry) { $result.Id = "dry-run"; $result.Added = $found.Count; return $result }

        $create = Invoke-Op -Arguments @("group", "create", $group, "--format=json") -What "create group $group" -Config $config
        $result.Retries.AddRange($create.Retries)
        if (-not $create.Ok) { $result.Err = $create.Err; return $result }
        $result.Id = ($create.Out | ConvertFrom-Json).id
        $result.Log.Add(@("CREATED", "group $group", ""))
        foreach ($email in $found) {
            $add = Invoke-Op -Arguments @("group", "user", "grant", "--group", $result.Id, "--user", $users[$email].id) `
                             -What "add $email to $group" -Config $config
            $result.Retries.AddRange($add.Retries)
            if ($add.Ok) { $result.Added++; $result.Log.Add(@("ADDED", "$email to group $group", "")) }
            else { $result.Log.Add(@("FAILED", "add $email to group $group", $add.Err)) }
        }
        return $result
    } | ForEach-Object {
        Write-Retries $_.Retries
        foreach ($entry in $_.Log) { Write-Audit $entry[0] $entry[1] @($entry[2] | Where-Object { $_ }) }
        if ($_.Id) {
            $created[$_.Group] = $_.Id
            $mark = if ($DryRun) { "$Yellow•$Reset" } else { "$Green✓$Reset" }
            $verb = if ($DryRun) { "would add" } else { "added" }
            Write-Say "  $mark $Bold$($_.Group)$Reset  $Dim$verb $($_.Added) of $($_.Total) member(s)$Reset"
        } else {
            Write-Audit "FAILED" "create group $($_.Group)" @($_.Err)
            $Issues.Add((New-Issue "failed" "" "group" $_.Group @() "couldn't create group: $($_.Err)"))
            Write-Say "  $Red✗$Reset $Bold$($_.Group)$Reset  ${Dim}couldn't create it, see the report$Reset"
        }
    }
    return $created
}


# Makes every grant on 10 threads, keeping failures for the report instead of printing them
function Grant-All {
    param($Tasks, $Issues)
    $done = 0
    Start-Progress "Assignments" $Tasks.Count
    $opDef = ${function:Invoke-Op}.ToString()
    $config = $OpConfig
    $dry = [bool]$DryRun

    $Tasks | ForEach-Object -ThrottleLimit $Threads -Parallel {
        ${function:Invoke-Op} = $using:opDef
        $task = $_
        if ($using:dry) { return [pscustomobject]@{ Task = $task; Err = ""; Retries = @() } }
        $arguments = @("vault", $task.Kind, "grant", "--vault", $task.VaultId, "--$($task.Kind)", $task.Id,
                       "--permissions", ($task.Perms -join ","))
        $r = Invoke-Op -Arguments $arguments -What "grant $($task.Kind) $($task.Name) on $($task.VaultName)" -Config $using:config
        return [pscustomobject]@{ Task = $task; Err = $(if ($r.Ok) { "" } else { $r.Err }); Retries = $r.Retries }
    } | ForEach-Object {
        Step-Progress
        Write-Retries $_.Retries
        $t = $_.Task
        $subject = "$($t.VaultName) / $($t.Kind) $($t.Name)"
        if ($_.Err) {
            Write-Audit "FAILED" $subject @($_.Err)
            $Issues.Add((New-Issue "failed" $t.VaultName $t.Kind $t.Name $t.Perms $_.Err))
        } else {
            Write-Audit $(if ($DryRun) { "WOULD GRANT" } else { "GRANTED" }) $subject @($t.Perms -join ", ")
            $done++
        }
    }
    Stop-Progress "$done of $($Tasks.Count) $(if ($DryRun) { 'ready' } else { 'done' })"
    return $done
}


# Writes the report of everything that couldn't be recreated
function Write-Report {
    param($Issues)
    $Issues | Sort-Object category, { $_.vault.ToLower() }, { $_.name.ToLower() } |
        Select-Object vault, type, name, permissions, reason |
        Export-Csv -Path $ReportPath -NoTypeInformation -UseQuotes AsNeeded -Encoding utf8
}


# Shows what couldn't be done as one line per kind of problem, with the details left to the report
function Show-Issues {
    param($Issues)
    if (-not $Issues.Count) { return }
    Write-Heading "Couldn't recreate"
    $rows = @(
        @("vault", "Vaults not found", { $_.vault }, $Yellow),
        @("user", "Users not found", { $_.name }, $Yellow),
        @("group", "Groups not found", { $_.name }, $Yellow),
        @("failed", "Failed", { if ($_.vault) { "$($_.vault) / $($_.name)" } else { $_.name } }, $Red),
        @("skipped", "Skipped (Recovery)", { $_.vault }, $Dim)
    )
    foreach ($row in $rows) {
        $category, $label, $nameOf, $color = $row
        $matching = @($Issues | Where-Object { $_.category -eq $category })
        if (-not $matching.Count) { continue }
        $names = @($matching | ForEach-Object $nameOf | Sort-Object -Unique)
        Write-Host ("  $color{0,-22}$Reset{1,4}   $Dim{2}$Reset" -f $label, $names.Count, (Format-Names $names))
    }
}


# Prints the totals and where the logs went, and returns the exit code
function Show-Summary {
    param([int]$Granted, [int]$Created, $Issues)
    $failed = @($Issues | Where-Object { $_.category -eq "failed" }).Count
    $notPossible = @($Issues | Where-Object { $_.category -notin @("failed", "skipped") }).Count
    $took = ((Get-Date) - $RunStarted).TotalSeconds

    Write-Heading "Summary"
    Write-Host ("  $Green✓$Reset {0,-26}{1,5}" -f $(if ($DryRun) { "Would assign" } else { "Assigned" }), $Granted)
    if ($Created) {
        Write-Host ("  $Green✓$Reset {0,-26}{1,5}" -f $(if ($DryRun) { "Groups to create" } else { "Groups created" }), $Created)
    }
    Write-Host ("  $(if ($notPossible) { $Yellow } else { $Dim })!$Reset {0,-26}{1,5}" -f "Missing in this account", $notPossible)
    Write-Host ("  $(if ($failed) { $Red } else { $Dim })✗$Reset {0,-26}{1,5}" -f "Failed", $failed)
    Write-Host ("  ${Dim}Took {0:N1}s$Reset" -f $took)
    Add-Content -Path $AuditPath -Encoding utf8 -Value @("",
        ("Finished   $Granted assigned, $Created group(s) created, $notPossible missing, $failed failed, took {0:N1}s" -f $took))

    $folder = [System.IO.Path]::GetRelativePath((Get-Location).Path, $LogsDir)
    Write-Heading "Logs"
    Write-Host "  $folder/"
    Write-Host ("    {0,-24}$Dim{1}$Reset" -f "audit.log", "every group created and permission granted")
    if ($Issues.Count) {
        Write-Host ("    {0,-24}$Yellow{1}$Reset" -f "not_recreated.csv", "$($Issues.Count) assignment(s) that couldn't be recreated")
    }
    Write-Host ""
    return $(if ($failed) { 1 } else { 0 })
}


# Shows who we're running as and stops if the CLI isn't signed in
function Show-Header {
    param([string]$Mode)
    $r = Invoke-Op -Arguments @("whoami", "--format=json") -What "whoami" -Config $OpConfig
    if (-not $r.Ok) { Stop-Script "Not signed in to 1Password ($($r.Err)). Run op signin first." }
    $me = $r.Out | ConvertFrom-Json
    $title = "Recreate vault permissions"
    $line = "─" * ($title.Length + 4)
    Write-Host "`n$Cyan╭$line╮$Reset`n$Cyan│$Reset  $Bold$title$Reset  $Cyan│$Reset`n$Cyan╰$line╯$Reset"
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "Account", ($me.url -replace '^https://', '').TrimEnd("/"))
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "Signed in", $me.email)
    Write-Host ("  $Dim{0,-11}$Reset{1}" -f "From", $File)
    Write-Host ("  $Dim{0,-11}$Reset$(if ($Mode -eq 'Live') { $Green } else { $Yellow }){1}$Reset" -f "Mode", $Mode)
    return $me
}


# Runs the whole thing
function Main {
    $mode = if ($DryRun) { "Dry run" } else { "Live" }
    $me = Show-Header $mode
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    Set-Content -Path $AuditPath -Encoding utf8 -Value @(
        "Recreate vault permissions",
        "Started    $($RunStarted.ToString('yyyy-MM-dd HH:mm:ss'))",
        "Signed in  $($me.email)",
        "Account    $($me.url)",
        "From       $((Resolve-Path $File -ErrorAction SilentlyContinue) ?? $File)",
        "Mode       $mode",
        "")

    Write-Heading "Reading"
    $source = Read-SourceCsv $File
    $userCount = @($source.Vaults.Values | ForEach-Object { $_.Users.Keys } | Sort-Object -Unique).Count
    $groupCount = @($source.Vaults.Values | ForEach-Object { $_.Groups.Keys } | Sort-Object -Unique).Count
    Write-Field "CSV" "$($source.Rows) rows, $($source.Vaults.Count) vaults, $userCount direct users, $groupCount groups"
    $destination = Read-Destination

    $create = [bool]$CreateGroups
    if (-not $create -and -not $NoCreateGroups) {
        $create = Request-CreateGroups (Get-CreatableGroups $source $destination.Groups)
    }

    $plan = Get-Plan $source $destination $create
    $tasks = $plan.Tasks
    $issues = $plan.Issues
    $matched = @($tasks | ForEach-Object { Get-BaseName $_.VaultName } | Sort-Object -Unique).Count
    Write-Heading "Plan"
    Write-Field "Vaults matched" "$matched of $($source.Vaults.Count)"
    Write-Field "Assignments to make" $tasks.Count
    if ($plan.ToCreate.Count) { Write-Field "Groups to create" $plan.ToCreate.Count }

    $created = @{}
    if ($plan.ToCreate.Count) {
        $created = New-Groups $plan.ToCreate $source $destination $issues
        foreach ($t in $tasks) { if (-not $t.Id) { $t.Id = $created[$t.Name] } }
        foreach ($t in @($tasks | Where-Object { -not $_.Id })) {
            $issues.Add((New-Issue "failed" $t.VaultName "group" $t.Name $t.Perms "group couldn't be created"))
        }
        $tasks = @($tasks | Where-Object { $_.Id })
    }

    Write-Heading $(if ($DryRun) { "Would assign" } else { "Assigning" })
    $granted = 0
    if ($tasks.Count) { $granted = Grant-All $tasks $issues } else { Write-Host "  ${Dim}Nothing to assign$Reset" }
    if ($issues.Count) { Write-Report $issues }
    Show-Issues $issues
    exit (Show-Summary $granted $created.Count $issues)
}

Main
