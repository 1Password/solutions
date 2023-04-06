# PowerShell import scripts

This folder contains some example scripts for creating vaults, items, user, and groups from CSV files using PowerShell:

|File | Description |
|:----|:------------|
|[`Import-Main.ps1`](./Import-Main.ps1)|Prepare environment for import|
|[`CreateVaults.ps1`](./CreateVaults.ps1)|Create vaults based on item and username|
|[`CreateGroups.ps1`](./CreateGroups.ps1)|Create groups from CSV|
|[`CreateItems.ps1`](./CreateItems.ps1)|Create items from CSV in vaults|
|[`AssignVaults.ps1`](./AssignVaults.ps1)|Assign vault permissions to groups|
|[`ProvisionUsers.ps1`](./ProvisionUsers.ps1)|Provision users from CSV|
|[`AssignGroupMemberships.ps1`](./AssignGroupMemberships.ps1)|Assign users to groups from CSV|
|[`CleanUp.ps1`](./CleanUp.ps1)|Remove vault permissions for CLI user|

## Prerequisites

- PowerShell 7 (see [Install PowerShell on Windows, Linux, and macOS](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell?view=powershell-7.3))
- 1Password CLI (see [Get started with 1Password CLI](https://developer.1password.com/docs/cli/get-started))
- a [1Password Business](https://support.1password.com/explore/business/) subscription or trial

The example scripts are based on a bespoke use case for a customer, and is intended to be run in the order above (with the expection of the [`Import-Main.ps1`](./Import-Main.ps1) script that is automatically invoked by all others and need not be run on its own).

Some steps can be run concurrently, but vaults must be created before items, users must be created before they can be assigned to groups, and groups and vaults must be created before assigning group memberships and vault permissions.

These scripts will create items, vaults, users, and groups from CSV files according to the following schema:

- items will be created in individual vaults
- vaults will be named based on the item title concatenated with the item username, e.g. `ItemTitle_UserName`
- groups will be created based on a list
- vault permissions will be assigned based on the group name and its suffix
- users will be provisioned based on name and email address
- users will be added to groups based on a list

> **Warning**
>
> CSV files should be saved with UTF-8 encoding. In Microsoft Excel, use the `CSV UTF-8 (Comma delimited) (.csv)` file type when saving.

This example allows for data to be imported from a third-party source with permissions set up in advance. When users join the 1Password account, they should have access to the correct items.

File paths and names can be customized using variables in [`Import-Main.ps1`](./Import-Main.ps1). Column names that represent fields to be consumed by the script can be customized using variables in each script.

The scripts create and read from lookups that are cached to disk. These are used to operate on object IDs rather than referencing by name for performance and rate limiting.

These scripts have been tested in PowerShell 7 on Windows and macOS (presumably they should also work on Linux).
