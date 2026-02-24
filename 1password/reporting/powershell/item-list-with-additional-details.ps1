# Requires 1Password CLI (`op`)
# CSV output format: item_UUID, Item_Name, Vault_UUID, Vault_Name, Primary_Url, Updated_At, link to item

function Get-Account-Details {
    $json = op whoami --format=json | ConvertFrom-Json
    return $json
}

$account_details = Get-Account-Details
$signin_address = ([uri]$account_details.url).Host
$acct_uuid = $account_details.account_uuid

$items = op item ls --format=json |
ConvertFrom-Json |
Where-Object { $_.category -eq 'LOGIN' } |

# add primary_url and link
ForEach-Object {
    $primary = $null
    if ($_.urls) {
        $primary = ($_.urls | Where-Object { $_.primary -eq $true } | Select-Object -First 1)
    }

    # create/augment object (non-destructive)
    [PSCustomObject]@{
        id                     = $_.id
        title                  = $_.title
        version                = $_.version
        category               = $_.category
        last_edited_by         = $_.last_edited_by
        created_at             = $_.created_at
        updated_at             = $_.updated_at
        additional_information = $_.additional_information
        primary_url            = if ($primary) { $primary.href } else { $null }
        link                   = "https://start.1password.com/open/i?a=$acct_uuid&v=$($_.vault.id)&i=$($_.id)&h=$signin_address"
        vault_id               = $_.vault.id
        vault_name             = $_.vault.name
    }
} |
Sort-Object -Property title

# Export CSV by piping objects into Export-Csv
$items | Export-Csv -Path .\items.csv -NoTypeInformation -Encoding UTF8