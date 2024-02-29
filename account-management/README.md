# Account management scripts

## Introduction

These examples are intended to demonstrate how the 1Password command line tool can help you gain visibility and insight into your 1Password account.  

## Script Descriptions

### [`vault-details.sh`](./vault-details.sh)

When run by a member of the Owners group, this script provides the vault name, the number of items in the vault, the last time the vault contents were updated, and list which users and groups have access to that vault along with their permissions.

When run by a non-Owner, it will provide these details for all vaults the user running the script has access to.

### [`remove-export-all-groups-and-vaults.sh`](./remove-export-all-groups-and-vault.sh)

When run by a member of the Owners group, this script will remove the `export items` permission for every vault that every group has access to without exception.

When run by a non-Owner, this script will remove the `export` permission on vaults that the person running the script also has the `manage vault` permissions for.

### [`vault-permission-change.sh`](./vault-permission-change.sh)

This script, when run by an a user with the `manage vault` (manage access) permission, will remove or add the specified vault permission(s) for the specified group(s) from all vaults (excluding Private vaults). This could be useful if you are looking to systematically remove the Administrators `manage vault` (manage access) permission from all created shared vaults, this leaving this permission to the default owners group. 

### [`vault-permission-change.py`](./vault-permission-change.py)

> ⚠️ **Warning**  
> Currently, you must use version 2.21 or older of the 1Password CLI when running these scripts. Version 2.22 and newer introduced changes that prevent these scripts from performing as-expected. Download version 2.21 the 1Password website [here](https://app-updates.agilebits.com/product_history/CLI2#v2210002).

Similar to [`vault-permission-change.sh`](#vault-permission-changesh) above, but with several additional options. It is also written in Python for greater cross-compatibility. 

When run by a member of the Owners group, for each vault the person running the script has at "Manage Vault" permissions for, the specified permission(s) will be removed from all people or groups assigned to the vault. Permissions for Owners and Administrators groups are not affected. Using the `--grant` or `-g` option will grant the specified permissions instead of revoking them.  

If a permission [has dependencies on other permissions](https://developer.1password.com/docs/cli/vault-permissions/), the script will automatically grant or revoke the dependent permissions. 

The script accepts the following options:

`--permission -p` Required. Use one or more times to specify a permission to be added or removed. This option can be specified an arbitrary number of times. A list of permissions is listed in the script's Help, or [learn more about vault permissions](https://developer.1password.com/docs/cli/vault-permissions/)
`--grant -g` Optional. Grants, rather than revokes, the specified permissions. 
`--as-admin` Optional. Use this flag if the person running the script is a member of the Administrators group, not the Owners group.

### [`bulk-group-prefix-update.sh`](./bulk-group-prefix-update.sh)

This script, when run by an Owner or Administrator, will change the prefix of all group names according to your specifications. This is particularly helpful if you are needing to change an existing naming scheme.
If you want to add prefixes where one doesn't already exist, then you can modify the `sed` substitution to: `sed 's/^/PREFIX/g'` to add a prefix to all groups.
This does not change the name of any built in groups (e.g., "Administrators", "Owners", "Team Members").

### [`compliance-export.sh`](./compliance-export.sh)

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
