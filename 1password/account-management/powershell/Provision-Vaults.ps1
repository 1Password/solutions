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
    [string[]]$Args = @(),     # e.g. @("MyVault","--format=json")
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
    foreach ($a in $Args) { $psi.ArgumentList.Add($a) }
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
        if ($stdout.Trim().Length -gt 0) { return $stdout | ConvertFrom-Json } else { return $null }
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

function Ensure-Vault {
  param([string]$VaultName)
  try {
    [void](Invoke-Op -Command "vault" -Args @("get", $VaultName, "--format=json") -JsonOut)
    return $true
  } catch {
    if ($_.Exception.Message -match 'not found') {
      if ($DryRun) { Write-Host "[DryRun] Would create vault '$VaultName'"; return $false }
      [void](Invoke-Op -Command "vault" -Args @("create", $VaultName, "--format=json") -JsonOut)
      return $true
    } else { throw }
  }
}

function Grant-UserPerms {
  param(
    [string]$VaultName,
    [string]$UserIdentifier,
    [string[]]$Permissions # or @('owner') sentinel
  )

  if ($Permissions.Count -eq 1 -and $Permissions[0] -eq 'owner') {
    # Prefer role owner if supported
    $args = @("user","grant","--vault",$VaultName,"--user",$UserIdentifier,"--role","owner")
    if ($DryRun) { Write-Host "[DryRun] Would grant OWNER role to user '$UserIdentifier' on '$VaultName'"; return }
    try {
      [void](Invoke-Op -Command "vault" -Args $args)
      return
    } catch {
      # Fallback to full perms if role not allowed
      Write-Host "OWNER role grant failed for '$UserIdentifier' on '$VaultName'. Falling back to full permissions."
      $Permissions = @('manage','view','create','edit','delete','copy','share','archive','import','export','view_items','edit_items') | Select-Object -Unique
    }
  }

  $permArgs = @()
  foreach ($p in $Permissions) { $permArgs += @("--permissions",$p) }
  $args = @("user","grant","--vault",$VaultName,"--user",$UserIdentifier) + $permArgs
  if ($DryRun) { Write-Host "[DryRun] Would grant perms [$($Permissions -join ',')] to user '$UserIdentifier' on '$VaultName'"; return }
  [void](Invoke-Op -Command "vault" -Args $args)
}

function Grant-GroupPerms {
  param(
    [string]$VaultName,
    [string]$GroupIdentifier,
    [string[]]$Permissions
  )
  $permArgs = @()
  foreach ($p in $Permissions) { $permArgs += @("--permissions",$p) }
  $args = @("group","grant","--vault",$VaultName,"--group",$GroupIdentifier) + $permArgs
  if ($DryRun) { Write-Host "[DryRun] Would grant perms [$($Permissions -join ',')] to group '$GroupIdentifier' on '$VaultName'"; return }
  [void](Invoke-Op -Command "vault" -Args $args)
}

# ---------- Permissions requested ----------
$OwnerSpec      = @('owner')                       # prefers role=owner; falls back to full perms
$MemberPerms    = @('manage','view','copy')
$AdminGroupPerm = @('manage')

# ---------- Process CSV ----------
$rows = Import-Csv -LiteralPath $CsvPath
$processed = 0

foreach ($row in $rows) {
  $vault   = ($row.VaultName   | ForEach-Object { $_.Trim() })
  $owner   = ($row.Owner       | ForEach-Object { $_.Trim() })
  $members = Split-List $row.Members
  $adminGp = ($row.AdminGroup  | ForEach-Object { $_.Trim() })

  if ([string]::IsNullOrWhiteSpace($vault)) { Write-Warning "Row skipped: VaultName missing."; continue }
  if ([string]::IsNullOrWhiteSpace($owner)) { Write-Warning "Row for vault '$vault' skipped: Owner missing."; continue }

  Write-Host "Processing vault '$vault'..."

  # Create or get vault
  [void](Ensure-Vault -VaultName $vault)

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