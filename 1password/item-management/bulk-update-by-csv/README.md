# 1Password Item Updater Script

This Python script automates the process of updating passwords for items stored in your 1Password vaults using the 1Password Command Line Interface (op). It reads item details and new passwords from a CSV file and applies the changes.

## Features

- Updates passwords for specified 1Password items
- Reads input data from a CSV file
- Identifies the correct password field to update (prioritizes primary password fields, then generic concealed fields)
- Uses the official 1Password CLI (op) for secure interaction with your vaults
- Provides console output for progress and error reporting

## Prerequisites

- **1Password Account**: You need an active 1Password account
- **1Password CLI (op)**: The 1Password Command Line Interface must be installed and configured on your system
- **Signed into op CLI**: You must be signed into your 1Password account via the op CLI. You can do this by running `op signin` and following the prompts. If you use biometric unlock, ensure it's enabled for the CLI
- **Python 3**: Python 3.6 or newer is required to run the script
- **CSV File**: A CSV file containing the items to update, formatted as described below

## CSV File Format

The script expects a CSV file with the following exact column headers:

- `vault`: The name of the 1Password vault containing the item
- `item title`: The exact title of the item in 1Password
- `new password`: The new password to set for the item

### Example CSV (passwords_to_update.csv)

```bash
vault,item title,new password
Personal,My Website Login,aVeryStrongNewPassword123!
Work,Server SSH Key,anotherSecureP@ssw0rd
Shared Vault,Database Credentials,"complex_p@$$wOrd_with_commas,and_quotes"
```

### Notes on CSV format

- The header row is mandatory and must match the names above
- If a new password (or any other field) contains a comma, enclose the entire field value in double quotes (`"`)

## Installation & Setup

1. Download the Script: Save the Python script (e.g., `update_op_passwords.py`) to your local machine
2. Make it Executable (Optional but Recommended for Linux/macOS):

   ```bash
   chmod +x update_op_passwords.py
   ```

3. Prepare your CSV file as described in the "CSV File Format" section

## Usage

Run the script from your terminal, providing the path to your CSV file as a command-line argument:

Using python3:

```bash
python3 update_op_passwords.py /path/to/your/passwords_to_update.csv
```

If you made it executable (Linux/macOS):

```bash
./update_op_passwords.py /path/to/your/passwords_to_update.csv
```

The script will then:

1. Verify it can connect to the op CLI
2. Read each row from your CSV file
3. For each item:
   - Fetch the item details from the specified vault
   - Identify the appropriate concealed field (password field)
   - Update the field with the new password from the CSV
4. Print progress messages or any errors encountered to the console

## How it Identifies the Password Field

The script attempts to find the correct field to update using the following logic:

1. It looks for a field explicitly marked with `purpose: "PASSWORD"` in the item's JSON structure (this is common for Login items)
2. If no such field is found, it looks for the first field with `type: "CONCEALED"`
3. It constructs the necessary field designator for the `op item edit` command, including the section name if the field is part of a section (e.g., `Section Name.Field Label` or just `Field Label`)

If you need to update a specific custom concealed field when multiple exist and none are marked as the primary password, this script might need modification.

## Important Considerations & Warnings

- **BACKUP YOUR VAULT DATA**: Before running any script that modifies your 1Password data, ensure you have a reliable backup or are comfortable with the changes. Use this script at your own risk.
- **Test Carefully**: It's highly recommended to test the script with a single, non-critical item first to ensure it behaves as expected in your environment.
- **Security of CSV File**: The new password column in your CSV file contains sensitive information in plaintext.
  - Store this file securely
  - Restrict access to it
  - Consider deleting the file or at least the new password column after the update process is successfully completed and verified
- **Error Handling**: The script includes basic error handling. Pay close attention to any error messages printed in the console, as they can help diagnose issues (e.g., item not found, incorrect vault name, op CLI problems).
- **Rate Limiting**: While generally not an issue for typical CLI usage, updating an extremely large number of items very rapidly could potentially encounter rate limits from the 1Password service.
- **Exact Item Titles**: The script relies on exact matches for "item title". Ensure these are correct in your CSV.

## Troubleshooting

- **'op' command not found**: Ensure the 1Password CLI is installed and its location is in your system's PATH environment variable.
- **Error: 1Password CLI 'op account list' command failed**: You are likely not signed into the op CLI. Run `op signin` and complete the authentication process.
- **Item not found / Vault not found**: Double-check the vault and item title entries in your CSV file for typos or case sensitivity issues. Vault and item names must be exact.
- **Could not find a suitable concealed field**: The item specified might not have any fields of type "CONCEALED", or the script could not identify one. Check the item structure in 1Password.

## Disclaimer

This script is provided as-is, without any warranty. Always exercise caution when automating actions on sensitive data.
