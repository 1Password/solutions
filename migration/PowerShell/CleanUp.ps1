# Remove op user from all vaults

# Set up environment
. $( Join-Path $PSScriptRoot -ChildPath 'Import-Main.ps1' )

$null = $vaultLookup.GetEnumerator() |
    ForEach-Object -Begin {
        $vaultLookup ??= Get-Content -Raw $vaultLookupFile | ConvertFrom-Json -AsHashtable
        $opUserUuid = (& $op whoami | ConvertFrom-Json).user_uuid
    } -Process {
        $vaultUuid = $_.Value
        $vaultUserRevocation = @(
                "--vault=$vaultUuid"
                "--user=$opUserUuid"
            )
        & $op vault user revoke @vaultUserRevocation --no-input
    }
