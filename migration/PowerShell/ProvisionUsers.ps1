# Provision users

# Set up environment
. $( Join-Path -Path $PSScriptRoot -ChildPath 'Import-Main.ps1' )

$userDataColumns = @{
    Name  = 'NAME'
    Email = 'EMAIL_ADDRESS'
}

$userDataFile = Join-Path -Path $csvPath -ChildPath $csvFileNames.UserData -Resolve

Import-Csv -Path $userDataFile |
    ForEach-Object -Begin {
        if ([System.IO.File]::Exists($userLookupFile)) {
            # Load lookup from file if it exists
            $userLookup = Get-Content -Raw $userLookupFile | ConvertFrom-Json -AsHashtable
        } else {
            # Initialize lookup table if not
            $userLookup ??= @{}
        }
    } -Process {
        $userName = $_.($userDataColumns.Name)
        $userEmail = $_.($userDataColumns.Email)
        $user = @(
            "--name=$userName"
            "--email=$userEmail"
        )
        # Provision user and index UUID in user lookup
        $userUuid = (& $op user provision @user | ConvertFrom-Json).id
        $userLookup.$userEmail = $userUuid
    } -End {
        # Cache (non-empty user lookup to disk
        if ($userLookup.Count -gt 0) {
            $userLookup | ConvertTo-Json -Compress | Out-File -FilePath $userLookupFile
        }
    }
