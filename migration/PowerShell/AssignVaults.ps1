# Grant vault permissions to groups

# Set up environment
. $( Join-Path $PSScriptRoot -ChildPath 'Import-Main.ps1' )

$vaultGroupColumns = @{
    GroupName  = 'GroupName'
}

 # Define permission sets as hashtable
 $vaultPermissions = @{
    ReadOnly  = @(
        'allow_viewing'
        # (or other permissions, one per line)
    )
    ReadWrite = @(
        'allow_viewing'
        'allow_editing'
        # (or other permissions, one per line)
    )
}

$groupsFile = Join-Path -Path $csvPath -ChildPath $csvFileNames.GroupData -Resolve

$null = Import-Csv -Path $groupsFile |
    ForEach-Object -Begin {
        # Load lookup tables from disk (if not in memory)
        $vaultLookup ??= Get-Content -Raw $vaultLookupFile | ConvertFrom-Json -AsHashtable
        $groupLookup ??= Get-Content -Raw $groupLookupFile | ConvertFrom-Json -AsHashtable
    } -Process {
        $groupName = $_.($vaultGroupColumns.GroupName)
        $groupPrefix = 'PSG-'
        $groupSuffix = switch -Wildcard ($groupName) {
            '*-ReadOnly' { '-ReadOnly'; Break }
            '*-ReadWrite' { '-ReadWrite' }
        }
        $vaultPattern = [regex]::Escape($groupPrefix) + '(?<vaultName>.*?)' + [regex]::Escape($groupSuffix)
        $vaultName = [regex]::Match($groupName, $vaultPattern).Groups['vaultName'].Value
        # Lookup UUIDs
        $vaultUuid = $vaultLookup.($vaultName)
        $groupUuid = $groupLookup.($groupName)
        $vaultGroupGrant = @(
            "--vault=$vaultUuid"
            "--group=$groupUuid"
            "--permissions=$(
                switch -Wildcard ($groupName) {
                    '*-ReadOnly' { $vaultPermissions.ReadOnly -join ','; Break }
                    '*-ReadWrite' { $vaultPermissions.ReadWrite -join ','}
                }
            )"
        )
        & $op vault group grant @vaultGroupGrant --no-input | ConvertFrom-Json -AsHashtable
    }
