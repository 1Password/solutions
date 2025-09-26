<# 
.SYNOPSIS
  Create/permission 1Password vaults from CSV.

.DESCRIPTION
  CSV headers: VaultName, Owner, Members, AdminGroup
  - Owner: user identifier (email or user ID). Granted OWNER role (or full perms fallback).
  - Members: ; or , or | separated user identifiers. Granted manage, view, copy.
  - AdminGroup: group name or ID. Granted manage only.

.REQUIREMENTS
  - 1Password CLI v2 (`op`) in PATH
  - Environment variable OP_SERVICE_ACCOUNT_TOKEN set to a valid Service Account token
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$CsvPath,

  [switch]$DryRun
)

# ---------- Safety checks ----------
if (-not (Get-Command op -ErrorAction SilentlyContinue)) {
  throw "1Password CLI 'op' not found in PATH."
}
if (-not $env:OP_SERVICE_ACCOUNT_TOKEN) {
  throw "OP_SERVICE_ACCOUNT_TOKEN not set. Set a Service Account token in the environment."
}
if (-not (Test-Path -LiteralPath $CsvPath)) {
  throw "CSV file not found: $CsvPath"
}

# ---------- Helpers ----------
function Split-List {
  param([string]$s)
  if ([string]::IsNullOrWhiteSpace($s)) { return @() }
  $delim = if ($s -match ';') {';'} elseif ($s -match '\|') {'|'} else {','}
  return ($s -split $delim | ForEach-Object { $_.Trim() }) | Where-Object { $_ -ne '' } | Select-Object -Unique
}

function Invoke-Op {
  param(
    [string]$Command,          # e.g. "vault get"
    [string[]]$opArgs = @(),     # e.g. @("MyVault","--format=json")
    [int]$MaxRetries = 8,
    [int]$BaseDelayMs = 400,   # base backoff
    [switch]$JsonOut
  )
  $attempt = 0
  while ($true) {
    $attempt++
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "op"
    $psi.ArgumentList.Add($Command)
    foreach ($a in $opArgs) { $psi.ArgumentList.Add($a) }
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $stdout = $p.StandardOutput.ReadToEnd()
    $stderr = $p.StandardError.ReadToEnd()
    $p.WaitForExit()

    if ($p.ExitCode -eq 0) {
      if ($JsonOut) {
        if ($stdout.Trim().Length -gt 0) {
          try {
            return $stdout | ConvertFrom-Json
          } catch {
            # Conversion failed — surface both stdout/stderr for debugging instead of returning invalid object
            throw "Failed to parse JSON from 'op $Command'. stdout:`n$stdout`nstderr:`n$stderr"
          }
        } else {
          return $null
        }
      } else {
        return $stdout
      }
    }

    # Detect rate limit or transient
    $isRate = ($stderr -match 'Too Many Requests' -or $stderr -match '\b429\b' -or $stderr -match 'rate\s*limit')
    $isTransient = ($stderr -match 'timeout' -or $stderr -match 'temporar' -or $stderr -match 'try again')
    if (($isRate -or $isTransient) -and $attempt -lt $MaxRetries) {
      $jitter = Get-Random -Minimum 100 -Maximum 400
      $delay = [math]::Min(20000, ($BaseDelayMs * [math]::Pow(2, $attempt-1))) + $jitter
      Start-Sleep -Milliseconds $delay
      continue
    }

    throw "op $Command failed (exit $($p.ExitCode)): $stderr"
  }
}

function Test-Vault {
  param([string]$VaultName)
  try {
    # Try to get the vault; JsonOut avoids noisy parsing errors
    [void](Invoke-Op -Command "vault" -opArgs @("get", $VaultName, "--format=json") -JsonOut)
    return $true
  } catch {
    $errMsg = $_.Exception.Message.ToString()
    # Match common "not found" / missing-vault messages from the CLI (case-insensitive)
    if ($errMsg -match '(?i)(not\s+found|no\s+such\s+vault|vault.*not.*found|Specify the vault)') {
      if ($DryRun) { Write-Host "[DryRun] Would create vault '$VaultName'"; return $false }
      Write-Host "Creating vault '$VaultName'..."
      [void](Invoke-Op -Command "vault" -opArgs @("create", $VaultName, "--format=json") -JsonOut)
      return $true
    } else {
      throw
    }
  }
}

function Grant-UserPerms {
  param(
    [string]$VaultName,
    [string]$UserIdentifier,
    [string[]]$Permissions # or @('owner') sentinel
  )

  $permArgs = @()
  foreach ($p in $Permissions) { $permArgs += @("--permissions",$p) }
  $opArgs = @("user","grant","--vault",$VaultName,"--user",$UserIdentifier) + $permArgs
  if ($DryRun) { Write-Host "[DryRun] Would grant perms [$($Permissions -join ',')] to user '$UserIdentifier' on '$VaultName'"; return }
  [void](Invoke-Op -Command "vault" -opArgs $opArgs)
}

function Grant-GroupPerms {
  param(
    [string]$VaultName,
    [string]$GroupIdentifier,
    [string[]]$Permissions
  )
  $permArgs = @()
  foreach ($p in $Permissions) { $permArgs += @("--permissions",$p) }
  $opArgs = @("group","grant","--vault",$VaultName,"--group",$GroupIdentifier) + $permArgs
  if ($DryRun) { Write-Host "[DryRun] Would grant perms [$($Permissions -join ',')] to group '$GroupIdentifier' on '$VaultName'"; return }
  [void](Invoke-Op -Command "vault" -opArgs $opArgs)
}

# ---------- Permissions requested ----------
$OwnerSpec      = @('allow_viewing,allow_editing,allow_managing')
$MemberPerms    = @('allow_managing,allow_viewing')
$AdminGroupPerm = @('allow_managing')

# ---------- Process CSV ----------
$rows = Import-Csv -LiteralPath $CsvPath
$processed = 0

foreach ($row in $rows) {
  # Trim directly (don't pipe a string into ForEach-Object — that enumerates characters)
  $vault   = if ($row.VaultName) { $row.VaultName.Trim() } else { '' }
  $owner   = if ($row.Owner)     { $row.Owner.Trim() }     else { '' }
  # Ensure members is always an array (wrap with @())
  $members = @(Split-List $row.Members)
  $adminGp = if ($row.AdminGroup) { $row.AdminGroup.Trim() } else { '' }

  if ([string]::IsNullOrWhiteSpace($vault)) { Write-Warning "Row skipped: VaultName missing."; continue }
  if ([string]::IsNullOrWhiteSpace($owner)) { Write-Warning "Row for vault '$vault' skipped: Owner missing."; continue }

  Write-Host "Processing vault '$vault'..."

  # Create or get vault
  [void](Test-Vault -VaultName $vault)

  # Owner
  Grant-UserPerms -VaultName $vault -UserIdentifier $owner -Permissions $OwnerSpec

  # Members
  foreach ($m in $members) {
    Grant-UserPerms -VaultName $vault -UserIdentifier $m -Permissions $MemberPerms
  }

  # Admin group
  if (-not [string]::IsNullOrWhiteSpace($adminGp)) {
    Grant-GroupPerms -VaultName $vault -GroupIdentifier $adminGp -Permissions $AdminGroupPerm
  }

  # Gentle pacing to avoid bursts
  Start-Sleep -Milliseconds (Get-Random -Minimum 250 -Maximum 750)
  $processed++
}

Write-Host "Done. Rows processed: $processed"