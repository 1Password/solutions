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

### [`remove-permissions-groups-and-vaults.py`](./remove-permissions-groups-and-vault.py)

#### Description
When run by a member of the Owners group, this script will remove permissions for every vault that any group you select has access to.

When run by a non-Owner, this script will remove your selected permissions on vaults that the person running the script also has the `manage vault` permissions for.


#### Requirements 
The Python script requires the `tqdm` package for progress bar functionality. Install it by running:
  ```
  pip install -r requirements.txt
  ```

