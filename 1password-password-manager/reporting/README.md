# Reporting Scripts

This directory provides a series of scripts demonstrating how to use the CLI to generate summary reports of vault access, contents, and permissions.

> 💡 **NOTE**  
> Many of these scripts require version 2.25 or newer of the 1Password CLI. Download the latest version [here](https://developer.1password.com/docs/cli/get-started).

## User vault access reports
The following scripts provide information about people who are directly granted access to vaults. It does not include groups.  

### [`user-access-list.py`](./user-access-list.py)
- Creates a csv file for each user in your 1Password account, and includes the following columns:
  - userName, userEmail, userUUID, userState, userCreatedAt, userUpdatedAt, directlyAssignedVaults, groups
  - where `userState` is their status (e.g., ACTIVE, SUSPENDED, etc), `directlyAssignedVaults` refers to vaults the user has been granted access to directly (not by group membership) and `groups` is a list of groups the person is a member of. 

If you need to review who has access to vaults both by direct assignment and group membership, see [vault-user-group-access-report.py](#vault-user-group-access-reportpy). 

### [`user-and-item-list.py`](./user-and-item-list.py)
- Creates a csv file of each user and item that has access to a list of vaults.
  - use `--file path/to/vaultlist` to provide a list of UUIDs, or use no flag to get a report for all vaults the Owners group has access to.
  - Columns included: "vaultName", "vaultUUD", "userName", "userEmail", "userUUID", "userPermissions", "itemName", "itemUUID"
  - This does not include users who have access to vaults as a result of membership in a group granted access to a vault. 

### [`vault-user-access-report.py`](./vault-user-access-report.py)

- Creates a csv file listing vaults, every user that has been directly granted access to each vault, and their permissions.
  - Use `--file path/to/vaultlist` to provide a list of UUIDs, or use no flag to get a report for all vaults the Owners group has access to.
  - Columns included: "vaultName", "vaultUUID", "name", "email", "userUUID", "userPermissions"
- This does NOT show users who have access to vaults as a result of their membership in an assigned group.


## User and group vault access reports
The following scripts provide information about vault access for both groups and individual users. Some scripts will decompose groups into their individual members, some may only provide information about the group itself.

### [`vault-user-group-access-report.py`](./vault-user-group-access-report.py)

- Creates a csv file listing vaults, every user that has been granted access to the vault directly or by virtue of their group membership, and their vault permissions.
  - Columns included: "vaultName", "vaultUUID", "userName", "userEmail", "userUUID", "userState", "assignment", "permissions"
    - "userState" indicates if the user is `ACTIVE`, `SUSPENDED`, `INVITED`, etc. a
    - "assignment" indicates whether they were directly assigned ("direct") or have access to a vault due to membership in an assigned group ("group(groupName)")
  - If users have access to a vault by multiple assignments (e.g., is directly assigned and a member of one or more group, or is a member of multiple groups all of which are assigned to the vault) they will appear on one row for every way they've been granted access. This can facilitate the identification of redundant assigments or unwanted permissions sprawl

