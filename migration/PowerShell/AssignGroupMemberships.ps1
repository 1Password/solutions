# Add users to groups

# Set up environment
. $( Join-Path $PSScriptRoot -ChildPath 'Import-Main.ps1' )

$userGroupColumns = @{
    EmailAddress  = 'EMAIL_ADDRESS'
    GroupName     = 'Group'
}

$userGroupFile = Join-Path -Path $csvPath -ChildPath $csvFileNames.GroupMemberData -Resolve

Import-Csv -Path $userGroupFile |
    ForEach-Object -Begin {
        # Load lookup tables from disk (if not in memory)
        $groupLookup ??= Get-Content -Raw $groupLookupFile | ConvertFrom-Json -AsHashtable
        $userLookup ??= Get-Content -Raw $userLookupFile | ConvertFrom-Json -AsHashtable
    } -Process {
        # Get group name, user email and lookup IDs
        $groupName = $_.($userGroupColumns.GroupName)
        $groupUuid = $groupLookup.$groupName
        $userEmail = $_.($userGroupColumns.EmailAddress)
        $userUuid = $userLookup.$userEmail
        # Create group assignment
        $groupUserGrant = @(
            "--group=$groupUuid"
            "--user=$userUuid"
        )
        # Assign user to group
        & $op group user grant @groupUserGrant
    }
