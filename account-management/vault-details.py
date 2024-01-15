#!/usr/bin/env python3
import subprocess
import json

def run_op_command(command, *args):
    try:
        result = subprocess.run(['op', command] + list(args), capture_output=True, check=True, text=True)
        return result #json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error executing 'op {command}': {e}")
        return None

def main():
    # Sign in to 1Password
    subprocess.run(['op', 'signin'], check=True)

    # Get list of vaults
    json_vault_list = run_op_command('vault', 'list', '--format=json')
    vault_list = json.loads(json_vault_list.stdout)
    if not vault_list:
        return

    for vault in vault_list:
        vault_id = vault['id']

        # Display Vault Details
        print("\n**************Vault Details**************")
        json_vault_details = run_op_command('vault', 'get', vault_id, '--format=json')
        vault_details = json.loads(json_vault_details.stdout)
        if vault_details:
            print(f"Name: {vault_details['name']}")
            print(f"Items: {vault_details['items']}")
            print(f"Last Updated: {vault_details['updated_at']}")

        # Display Users
        print("\n**************Users**************")
        users = run_op_command('vault', 'user', 'list', vault_id)
        print(users.stdout)

        # Display Groups
        print("\n**************Groups**************")
        groups = run_op_command('vault', 'group', 'list', vault_id)
        print(groups.stdout)

        print("\n*****************************************\n")

if __name__ == "__main__":
    main()