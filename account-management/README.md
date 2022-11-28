# Account management scripts
## Introduction
These examples are intended to demonstrate how the 1Password command line tool can help you gain visibility and insight into your 1Password account.  

## Script Descriptions
### [vault-details.sh](https://github.com/1Password/solutions/blob/main/account-management/vault-details.sh)
When run by a member of the Owners group, this script provides the vault name, the number of items in the vault, the last time the vault contents were updated, and list which users and groups have access to that vault along with their permissions.

When run by a non-Owner, it will provide these details for all vaults the user running the script has access to. 

### [remove-export-all-groups-and-vaults.sh](https://github.com/1Password/solutions/blob/main/account-management/remove-export-all-groups-and-vault.sh)
When run by a member of the Owners group, this script will remove the `export items` permission for every vault that every group has access to without exception. 

When run by a non-Owner, this script will remove the `export` permission on vaults that the person running the script also has the `manage vault` permissions for. 

### [bulk-group-prefix-update.sh](https://github.com/1Password/solutions/blob/main/account-management/bulk-group-prefix-update.sh)
This script, when run by an Owner or Administrator, will change the prefix of all group names according to your specifications. This is particularly helpful if you are needing to change an existing naming scheme.
If you want to add prefixes where one doesn't already exist, then you can modify the `sed` substitution to: `sed 's/^/PREFIX/g'` to add a prefix to all groups. 
This does not change the name of any built in groups (e.g., "Administrators", "Owners", "Team Members").

### [compliance-export.sh](https://github.com/1Password/solutions/blob/main/account-management/compliance-export.sh)
This script, when run by an adminstrator, will output all items within the specified scope (e.g., with a specific tag) as a long-formatted CSV. The export excludes any concealed fields such as password fields. 
This script may be helpful if you need to have someone verify the accuracy of the details of a 1Password item without revealing any secret values stored in that item. 

## Considerations
The majority of the scripts here are best if run by someone belonging to the Owners group in 1Password. This is because only the Owners group is guaranteed to have at least `manage vault` permissions on every shared vault in a 1Password Business account. Running these scripts as a user not in the Owners group may result in incomplete information or in changes not being made for all vaults. 

## Essential reading
In addition to the examples here, please review the complete documentation at developer.1password.com, especially:
* [op vault](https://developer.1password.com/docs/cli/reference/management-commands/vault)  
* [op group](https://developer.1password.com/docs/cli/reference/management-commands/group)  
* [op user](https://developer.1password.com/docs/cli/reference/management-commands/user)  

## Events API
If you use a security information and events monitoring (SIEM) tool, you may be interested in the [1Password Events API](https://support.1password.com/events-reporting/). 
