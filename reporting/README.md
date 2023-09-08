# Reporting Scripts

This directory provides a series of scripts demonstrating how to use the CLI to generate summary reports of vault access, contents, and permissions. 

## [`user-and-item-list.py`](./user-and-item-list.py)
* Creates a csv file of each user and item that has access to a list of vaults. 
  * use `--file path/to/vaultlist` to provide a list of UUIDs, or use no flag to get a report for all vaults the Owners group has access to. 
  * Columns included: "vaultName", "vaultUUD", "userName", "userEmail", "userUUID", "userPermissions", "itemName", "itemUUID"

## [`vault-access-report.py`](./vault-access-report.py)
* Creates a csv file listing vaults, every user user that has access to each vault, and their permissions. 
  * Use `--file path/to/vaultlist` to provide a list of UUIDs, or use no flag to get a report for all vaults the Owners group has access to. 
  * Columns included: "vaultName", "vaultUUID", "name", "email", "userUUID", "userPermissions"