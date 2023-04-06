# Create items in vaults

. $( Join-Path -Path $PSScriptRoot -ChildPath 'Import-Main.ps1' )

$itemDataFile = Join-Path -Path $csvPath -ChildPath $csvFileNames.ItemData -Resolve

## Set import data headings to use for 1Password vault and item attributes

$itemDataColumns = @{
    ItemTitle       = 'Resource Name'
    ItemUsername    = 'Account Name'
    ItemPassword    = $null             # Replace with password column for live password export
    ItemNotes       = 'ResourceDesc'
    ItemTags        = 'Resource Type'
}

# Create items in vaults

# Ingest CSV rows as 1Password item objects, pass to op via stdin, send local returned items to $null
$null = Import-Csv -Path $itemDataFile | ForEach-Object -Begin {
    $importDate = Get-Date -UFormat "%Y/%m/%d/%R"
    # Load lookup from disk (if not in memory)
    $vaultLookup ??= Get-Content -Raw $vaultLookupFile -ErrorAction Stop | ConvertFrom-Json -AsHashtable
} -Process {
    # Make a 1Password item object and send it down the pipeline to 1Password CLI
    [pscustomobject]@{
        title    = $_.($itemDataColumns.ItemTitle)
        vault    = [pscustomobject]@{
            id = $vaultLookup.("$( $_.($itemDataColumns.ItemTitle) )_$( $_.($itemDataColumns.ItemUsername) )")
        }
        category = 'LOGIN'
        tags     = [string[]]@(
            $_.($itemDataColumns.ItemTags)
            "CSV Import/$( $importDate )"
            
        )
        fields   = [pscustomobject[]]@(
            @{
                id      = 'username'
                type    = 'STRING'
                purpose = 'USERNAME'
                label   = 'username'
                value   = $_.($itemDataColumns.ItemUsername)
            }
            # To include passwords on import, use commented value instead of $null below
            @{
                id      = 'password'
                type    = 'CONCEALED'
                purpose = 'PASSWORD'
                label   = 'password'
                value   = $null         # $_.($itemDataColumns.ItemPassword)
            }
            @{
                id      = 'notesPlain'
                type    = 'STRING'
                purpose = 'NOTES'
                label   = 'notesPlain'
                value   = $_.($itemDataColumns.ItemNotes)
            }
        )
    } |
    ConvertTo-Json |
        # Create item in 1Password
        & $op item create - --generate-password # Remove --generate-password for import
}
