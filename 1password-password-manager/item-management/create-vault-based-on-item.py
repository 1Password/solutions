#!/usr/bin/python3
import subprocess
import json
from typing import List, Tuple


# This script will loop through vault specied in the vaultUUID variable. 
# For each item in this vault, it will create (without administrator group management permissions) 
# a new vault based off the name in the fieldvalue variable. 
# This could be a custom field such as "Company" in all the items in the vault being looped through.
# The original item, is then created in the new vault and removed from the original vault.

# This script was inspired by a use case where 1Password Connect is tied to a "landing" vault where new items 
# are being created through a web form for new clients/companies in this landing vault, where the new items
# are only stored until they are moved to a specific vault for the client/company.

#Change this value to the vault that you are moving items from, your landing vault.
vault_uuid="l4nypt4q3hc5nmrtef3a34qhpi"

#Change the value of this to match the corresponding field you are looking in the item in this landing vault.
field_name="username"

def run_op_command(args: List[str]) -> Tuple[str, str]:
    # Run a 1Password CLI command and return stdout, stderr
    cmd = ["op"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout, ""
    except subprocess.CalledProcessError as e:
        return "", e.stderr.strip() or f"Unknown CLI error (command: {' '.join(cmd)})"
    except FileNotFoundError:
        return "", "1Password CLI ('op') not found. Please ensure it is installed."


# creates new vault based of item detail from field from variable `fieldvalue` specified above. 
# The field must be valid for the specified vault.
def main():
    # Get list of item IDs in the vault
    item_list_json, error = run_op_command(["item", "list", "--vault", vault_uuid, "--format=json"])
    if item_list_json is None:
        print(f"\nFailed to get a list of items : {error}")
        exit(1)

    item_ids = [item["id"] for item in json.loads(item_list_json)]

    for item_id in item_ids:
        print(f"Working on item id: {item_id}")

        # Get the field value from the item
        field_value, error = run_op_command(["item", "get", item_id, "--fields", field_name])
        if not field_value:
            print(f"\nFailed to get field value from item '{item_id}' : {error}")
            continue

        # Create a new vault
        new_vault, error = run_op_command(["vault", "create", f"\"{field_value}\"", "--allow-admins-to-manage", "false", "--format", "json"])

        if not new_vault:
            print(f"\nFailed to create a vault for item '{item_id}' : {error}")
            continue
        new_vault_uuid = json.loads(new_vault)["id"]

        # Get item in JSON format and pipe it into op item create
        get_item_json, error = run_op_command(["item", "get", item_id, "--format", "json"])
        if not get_item_json:
            print(f"\nFailed to get item info for item '{item_id}' : {error}")
            continue
        get_item_json, error = run_op_command(["item", "get", item_id, "--format", "json"])
        create_item, error = run_op_command(["item", "create", f"--vault={new_vault_uuid}", get_item_json])
        
        # Archive the original item
        delete_item, error = run_op_command(["item", "delete", item_id, "--archive", "--vault", vault_uuid])


if __name__ == "__main__":
    main()