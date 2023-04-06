# Set up import environment and 1Password CLI

[System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Set up 1Password CLI
$op = (Get-Command 'op').Path

# Declare and set environment variables for piping data
$opEnvs = @{
    OP_FORMAT         = 'json'  # Format all output as JSON
    OP_NO_COLOR       = $true   # Return monocrhome text to avoid artifacts on Windows
    OP_ISO_TIMESTAMPS = $true   # Output ISO 8601 / RFC 3339 timestamps
}
foreach ($env in $opEnvs.GetEnumerator()) {
    Set-Item -Path (Join-Path -Path 'Env:' -ChildPath $env.Name) -Value $env.Value
}

# Set import data path
$csvPath = $PSScriptRoot

# Set filenames for import data
$csvFileNames = @{
    ItemData        = 'all_data.csv'        # List of items to create
    VaultGroupData  = 'groups.csv'          # List of vaults and associated groups
    UserData        = 'user_list.csv'       # User names and emails to provision
    GroupData       = 'groups.csv'          # Groups to create
    GroupMemberData = 'users-groups.csv'    # Group memberships
}

# Set a path for caching object UUID lookups
$lookupPath = $PSScriptRoot

$lookupFileNames = @{
    Vault = 'vaultLookup.json'  # Vault names 
    User  = 'userLookup.json'   # User emails
    Group = 'groupLookup.json'  # Group names
    # Item  = $null             # (Item titles, for example: $itemLookup.itemTitle = $itemUuid)
}

$userLookupFile = Join-Path -Path $lookupPath -ChildPath $lookupFileNames.User
$groupLookupFile = Join-Path -Path $lookupPath -ChildPath $lookupFileNames.Group
$vaultLookupFile = Join-Path -Path $lookupPath -ChildPath $lookupFileNames.Vault
