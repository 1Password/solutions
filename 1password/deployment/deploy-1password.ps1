<#
deploy-1password.ps1 

Purpose:
- Deploy the latest version of the 1Password Desktop app for Windows using Acronis RMM.
- Designed for unattended, silent deployment on Windows endpoints.
- Automatically fetches the latest version from the official 1Password URL.
- Verifies installation status to prevent redundant reinstalls.
- Logs details for Acronis RMM job output.

Usage example in Acronis RMM:
  powershell.exe -ExecutionPolicy Bypass -File 1Password_Deploy_AcronisRMM.ps1 -Force

Parameters:
  -Force       Force reinstallation even if already installed

  Prior work from Acronis MSI deployment. Added MSIX install and detection
#>


param(
    [switch]$Force
)

# --- Configuration ---
$AppName = "1Password"
$MsixDownloadUrl = "https://downloads.1password.com/win/1PasswordSetup-latest.msixbundle"
$MsixInstallerName = "1PasswordSetup-latest.msixbundle"
$MsiDownloadUrl = "https://c.1password.com/dist/1P/win8/1PasswordSetup-latest.msi"
$MsiInstallerName = "1PasswordSetup-latest.msi"
$TempDir = New-Item -ItemType Directory -Path ([IO.Path]::GetTempPath() + [IO.Path]::GetRandomFileName())

# --- Magic Numbers ---
# $msixRequiredBuild = 28000 #for testing
$msixRequiredBuild = 18363 # Windows 10 1909
# 1Password for Windows has two package family names, one for store and one for msix
$PackageFamilyNames = @("Agilebits.1Password_amwd9z03whsfe", "DC5C6510.2032887045529_2v019pwa6amcg")


# --- Logging Function ---
function Write-Log($Message, $Level = "INFO") {
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "$timestamp [$Level] $Message"
}

# --- Privilege Check ---
function Test-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

# --- Installation Detection ---
function Test-1PasswordInstalledExeOrMsi {
    $paths = @(
        "$env:ProgramFiles\1Password",
        "$env:ProgramFiles(x86)\1Password"
    )
    foreach ($p in $paths) {
        if (Test-Path $p) {
            Write-Log "Detected 1Password folder: $p"
            return $true
        }
    }

    $regPath = 'HKLM:SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    $regPathWow = 'HKLM:SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    foreach ($key in Get-ChildItem $regPath, $regPathWow -ErrorAction SilentlyContinue) {
        $disp = (Get-ItemProperty $key.PSPath -ErrorAction SilentlyContinue).DisplayName
        if ($disp -and $disp -match '1Password') { return $true }
    }
    return $false
}

function Test-1PasswordInstalledMsix {

    foreach ($n in $PackageFamilyNames) {
        if (Get-AppxPackage | Where-Object { $_.PackageFamilyName -Like $n }) {
            Write-Log "Detected 1Password installed as: $n"
            return $true
        }
    }
}

function Test-MsixCapable {
    $currentBuild = [System.Environment]::OSVersion.Version.Build
    return $currentBuild -ge $msixRequiredBuild
}

# --- Main Script ---
Write-Log "Starting $AppName deployment via Acronis RMM."

if (-not (Test-Admin)) {
    Write-Log "Warning: script is not running as Administrator." "WARN"
}

if (Test-MsixCapable) {
    Write-Log "System is MSIX capable (build $([System.Environment]::OSVersion.Version.Build) >= $msixRequiredBuild). Will attempt MSIX installation."
    $InstallerPath = Join-Path $TempDir.FullName $MsixInstallerName

    if ((Test-1PasswordInstalledExeOrMsi) -and -not $Force) {
        Write-Log "$AppName is already installed via EXE or MSI. Exiting (use -Force to reinstall)."
        exit 0
    }

    if ((Test-1PasswordInstalledMsix) -and -not $Force) {
        Write-Log "$AppName is already installed via msixbundle / MS Store. Exiting (use -Force to reinstall)."
        exit 0
    }

    try {
        $ProgressPreference = 'SilentlyContinue'
        Write-Log "Downloading latest $AppName installer from $MsixDownloadUrl"
        Invoke-WebRequest -Uri $MsixDownloadUrl -OutFile $InstallerPath -ErrorAction Stop
        Write-Log "Download completed: $InstallerPath"

        Write-Log "Starting silent installation..."
        Add-AppxPackage -Path $InstallerPath
        $ProgressPreference = 'Continue'

        Write-Log "$AppName installation completed successfully."


        exit 0
    }
    catch {
        Write-Log "Unhandled exception: $_" "ERROR"
        exit 99
    }
}
else {

    Write-Log "System is NOT MSIX capable (build $([System.Environment]::OSVersion.Version.Build) < $msixRequiredBuild). Will attempt MSI installation." "WARN"
    # we're not running on an msix capable environment, we're going to use MSI
    # We don't need to bother checking for MSIX now
    $InstallerPath = Join-Path $TempDir.FullName $MsiInstallerName
    if ((Test-1PasswordInstalledExeOrMsi) -and -not $Force) {
        Write-Log "$AppName is already installed via EXE or MSI. Exiting (use -Force to reinstall)."
        exit 0
    }

    if (-not (Test-Admin)) {
        Write-Log "Error: Administrator privileges are required to install 1Password via MSI. Exiting." "ERROR"
        exit 1
    }

    Write-Log "Info: installing 1Password for Windows using .msi. System integration for passkey filling and saving will not be available."

    try {
        $ProgressPreference = 'SilentlyContinue'
        Write-Log "Downloading latest $AppName installer from $MsiDownloadUrl"
        Invoke-WebRequest -Uri $MsiDownloadUrl -OutFile $InstallerPath -ErrorAction Stop
        $ProgressPreference = 'Continue'
        Write-Log "Download completed: $InstallerPath"

        Write-Log "Starting silent installation..."
        # Add-AppxPackage -Path $InstallerPath
        $Arguments = "/i `"$InstallerPath`" /qn /norestart"
        Start-Process -FilePath "msiexec.exe" -ArgumentList $Arguments -Wait -NoNewWindow


        Write-Log "$AppName installation completed successfully."


        exit 0
    }
    catch {
        Write-Log "Unhandled exception: $_" "ERROR"
        exit 99
    }
}