# Reporting Scripts

This directory provides a series of scripts demonstrating how to use the CLI to generate summary reports of vault access, contents, and permissions.

## [`user-and-item-list.py`](./user-and-item-list.py)

- Creates a csv file of each user and item that has access to a list of vaults.
  - use `--file path/to/vaultlist` to provide a list of UUIDs, or use no flag to get a report for all vaults the Owners group has access to.
  - Columns included: "vaultName", "vaultUUD", "userName", "userEmail", "userUUID", "userPermissions", "itemName", "itemUUID"

## [`vault-user-access-report.py`](./vault-user-access-report.py)

- Creates a csv file listing vaults, every user that has been directly granted access to each vault, and their permissions.
  - Use `--file path/to/vaultlist` to provide a list of UUIDs, or use no flag to get a report for all vaults the Owners group has access to.
  - Columns included: "vaultName", "vaultUUID", "name", "email", "userUUID", "userPermissions"
- This does NOT show users who have access to vaults as a result of their membership in an assigned group.

## [`vault-user-group-access-report.py`](./vault-user-group-access-report.py)

- Creates a csv file listing vaults, every user that has been granted access to the vault directly or by virtue of their group membership.
  - Columns included: "vaultName", "vaultUUID", "userName", "userEmail", "userUUID", "userState", "assignment"
    - "userState" indicates if the user is `ACTIVE`, `SUSPENDED`, `INVITED`, etc. a
    - "assignment" indicates whether they were directly assigned ("direct") or have access to a vault due to membership in an assigned group ("group(groupName)")
  - If users have access to a vault by multiple assignemtns (e.g., is directly assigned and a member of one or more group, or is a member of multiple groups all of which are assigned to the vault) they will appear on one row for every way they've been granted access. 