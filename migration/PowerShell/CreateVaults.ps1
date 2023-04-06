# Create vaults

# Set up environment
. $( Join-Path -Path $PSScriptRoot -ChildPath 'Import-Main.ps1' )

$itemDataFile = Join-Path -Path $csvPath -ChildPath $csvFileNames.ItemData -Resolve

# Set import data headings to use for 1Password vault and item attributes

$vaultDataColumns = @{
    ItemTitle        = 'Resource Name'
    ItemUsername     = 'Account Name'
    VaultDescription = 'ResourceDesc'
}

# Create vaults in 1Password (one per item)
Import-Csv -Path $itemDataFile |
    ForEach-Object -Begin {
        if ([System.IO.File]::Exists($vaultLookupFile)) {
            # Load lookup from file if it exists
            $vaultLookup = Get-Content -Raw $vaultLookupFile | ConvertFrom-Json -AsHashtable
        } else {
            # Initialize lookup table if not
            $vaultLookup ??= @{}
        }
    } -Process {
        # Construct vault name from item title and username
        $vaultName = "$( $_.($vaultDataColumns.ItemTitle) )_$($_.( $vaultDataColumns.ItemUsername) )"
        $vault = @(
            $vaultName
            "--description=$( $_.($vaultDataColumns.VaultDescription) )"
        )
        # Create item, get vault UUID and add to lookup
        $vaultUuid = (& $op vault create @vault | ConvertFrom-Json).id
        $vaultLookup.$vaultName = $vaultUuid
    } -End {
        # Cache (non-empty) lookup to disk
        if ($vaultLookup.Count -gt 0) {
            $vaultLookup | ConvertTo-Json -Compress | Out-File -FilePath $vaultLookupFile
        }
    }
