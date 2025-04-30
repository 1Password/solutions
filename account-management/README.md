# Account management scripts

## Introduction

These examples are intended to demonstrate how the 1Password command line tool can help you gain visibility and insight into your 1Password account.  

## Script Descriptions

### [`create_vaults_from_input.py`](./create_vaults_from_input.py)
This script will create a vault for each vault name in a file passed to the script with the `--file=` flag. Optionally remove your own access to the vault after creating it by running the script with the `--remove-me` flag. 

#### Usage
1. Install 1Password's CLI tool folowing the directions for your operating system here: https://developer.1password.com/docs/cli/get-started
2. In the 1Password desktop application enable the integration with the CLI, as documented here: https://developer.1password.com/docs/cli/get-started#step-2-turn-on-the-1password-desktop-app-integration
3. Open a terminal window and confirm:
  4. the 1Password CLI (called `op`) is installed and working, and the desktop application integration is enabled, by trying `op signin` and signing into the desired 1Password account. 
  5. Ensure that you have a version of python installed by running `python --version` or `python3 --version` (ideally you have at least python 3.7). 
6. Download this script to a folder on your computer (e.g., `~/Downloads`). 
7. In your terminal, move to that folder (e.g., `cd ~/Downloads`)
8. Run the script by executing `python3 create_vaults_from_input.py --file=path/to/input/list` 


#### Options
By default, when a person creates a vault, they are the "vault creator" and have full permissions for each vault they create. More than likely this will be desirable in your situation. 

However, if you'd like to have your access revoked so that you are not directly assigned to the vault after it's created, run the script using the `--remove-me` flag. 
* Note that even if you remove yourself from the vaults, members of the Owners and Administrators groups will still have "Manage Vault" permissions on these vaults, and will be able to manage their own or others' access to them. 
* To work around some current rate limiting issues related to permissions commands in the CLI, using the `--remove-me` flag will result in the script taking considerably longer to run (the script has an 11 second delay for each vault when modifying permissions to avoid rate limiting).

### [`vault-details.sh`](vault-details.sh)

When run by a member of the Owners group, this script provides the vault name, the number of items in the vault, the last time the vault contents were updated, and list which users and groups have access to that vault along with their permissions.

When run by a non-Owner, it will provide these details for all vaults the user running the script has access to.

### [`remove-permissions-groups-and-vaults.py`](remove-export-all-groups-and-vault.sh)

**Requirements**: The Python script requires the `tqdm` package for progress bar functionality. Install it by running:
  ```
  pip install -r requirements.txt
  ```

When run by a member of the Owners group, this script will remove permissions for every vault that any group you select has access to.

When run by a non-Owner, this script will remove your selected permissions on vaults that the person running the script also has the `manage vault` permissions for.

### [`vault-permission-change.sh`](vault-permission-change.sh)

This script, when run by an a user with the `manage vault` (manage access) permission, will remove or add the specified vault permission(s) for the specified group(s) from all vaults (excluding Private vaults). This could be useful if you are looking to systematically remove the Administrators `manage vault` (manage access) permission from all created shared vaults, this leaving this permission to the default owners group. 

### [`bulk-group-prefix-update.sh`](bulk-group-prefix-update.sh)

This script, when run by an Owner or Administrator, will change the prefix of all group names according to your specifications. This is particularly helpful if you are needing to change an existing naming scheme.
If you want to add prefixes where one doesn't already exist, then you can modify the `sed` substitution to: `sed 's/^/PREFIX/g'` to add a prefix to all groups.
This does not change the name of any built in groups (e.g., "Administrators", "Owners", "Team Members").

### [`compliance-export.sh`](compliance-export.sh)

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
