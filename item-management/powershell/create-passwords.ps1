# Requires: 1Password CLI (`op`) and service account token already configured
# CSV Format: Vault_Name,Login_Name,Vault_Item_Password_Name,Vault_Item_Uname,Vault_Item_Pass,Vault_Item_WebSite,
param (
    [string]$CsvPath = ".\import-items.csv",
    [string]$ServiceAccountToken
)
$logPath = "import-log-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
# Sign in using service account token
$env:OP_SERVICE_ACCOUNT_TOKEN = $ServiceAccountToken
# Import the CSV data
$items = Import-Csv -Path $csvPath
$Error.Clear()
# Function to log messages
function Write-Log-Message {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp`t$message" | Out-File -FilePath $logPath -Append -Encoding utf8
}
foreach ($item in $items) {
    # Extract values from the row
    $vault = $item.Vault_Name
    $title = $item.Vault_Item_Password_Name
    $username = $item.Vault_Item_Uname
    $password = $item.Vault_Item_Pass
    $url = $item.Vault_Item_WebSite
    # Create the JSON payload for the login item
    $loginItem = @{
        "title" = $title
        "category" = "LOGIN"
        "fields" = @(
            @{ "id" = "username"; "purpose" = "USERNAME"; "label" = "username"; "value" = $username; "type" = "STRING" },
            @{ "id" = "password"; "purpose" = "PASSWORD"; "label" = "password"; "value" = $password; "type" = "CONCEALED" }
        )
        "urls" = @(@{ "href" = $url })
    } | ConvertTo-Json -Depth 5
    $output = Write-Output $loginItem | op item create --vault "$vault" --format json 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Log-Message "Failed to create item '$title' in vault '$vault': $output"
        Write-Output "Failed to create item '$title' in vault '$vault': $output"
    }
    else {
        Write-Log-Message "Created item '$title' in vault '$vault'"
        Write-Output "Created item '$title' in vault '$vault'"
    }
   
}

Write-Output ""
Write-Output "The import process is complete. For details, review the log file at: $logPath"
Write-Output ""