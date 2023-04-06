# Create groups

# Set up environment
. $( Join-Path -Path $PSScriptRoot -ChildPath 'Import-Main.ps1' )

$groupDataColumns = @{
    GroupName        = 'GroupName'
    GroupDescription = 'Description'
}

$groupsFile = Join-Path -Path $csvPath -ChildPath $csvFileNames.GroupData -Resolve

Import-Csv -Path $groupsFile | ForEach-Object -Begin {
        # Get signed in user UUID
        $opUserUuid = (& $op whoami | ConvertFrom-Json).user_uuid
        if ([System.IO.File]::Exists($groupLookupFile)) {
            # Load lookup from file if it exists
            $groupLookup = Get-Content -Raw $groupLookupFile | ConvertFrom-Json -AsHashtable
        } else {
            # Initialize lookup table if not
            $groupLookup ??= @{}
        }
    } -Process {
        $groupName = $_.($groupDataColumns.GroupName)
        $groupDescription = $_.($groupDataColumns.GroupDescription)
        $group = @(
            $groupName
            "--description=$groupDescription"
        )
        # Create group and add ID to lookup
        $groupUuid = (& $op group create @group | ConvertFrom-Json).id
        $groupLookup.$groupName = $groupUuid
        # Remove signed in user from group
        $groupUserRevocation = @(
            "--group=$groupUuid"
            "--user=$opUserUuid"
        )
        & $op group user revoke @groupUserRevocation
    } -End {
        # Cache (non-empty) lookup to disk
        if ($groupLookup.Count -gt 0) {
            $groupLookup | ConvertTo-Json -Compress | Out-File -FilePath $groupLookupFile
        }
    }
