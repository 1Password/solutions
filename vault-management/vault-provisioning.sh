#!/usr/bin/env bash

# This example script automates vault provisioning based on these inputs:
# 
# - VAULT_NAME: the desired name of the vault to be created
# - VAULT_DESCRIPTION: text to describe the purpose of the vault
# - REQUESTER_EMAIL: 1Password email of a team member who is requesting a vault
# - REQUESTER_PERMISSIONS: vault permissions to be assigned to the requester
# - MANAGER_EMAIL: the team member who is approving the vault request
# - MANAGER_PERMISSIONS: vault permissions to be assigned to the approver
# - GROUP_NAME: the name of a 1Password group
# - GROUP_PERMISSIONS: vault permissions to be assigned to the group
#
# Permissions should be a comma-separated string. See:
# - https://developer.1password.com/docs/cli/vault-permissions
# - `op vault user grant --help`
# - `op vault group grant --help`
#
# The script assumes that 1Password CLI has been initialized on the device.
# The account password can optionally be passed from stdin.

# Use permissions from environment or fallback to below values
export REQUESTER_PERMISSIONS=${REQUESTER_PERMISSIONS:-"manage_vault"}
export MANAGER_PERMISSIONS=${MANAGER_PERMISSIONS:-"allow_viewing,allow_editing"}
export GROUP_PERMISSIONS=${GROUP_PERMISSIONS:-"allow_viewing,create_items,edit_items,archive_items,copy_and_share_items"}

extract_id_from_json () {
    echo "$@" | jq -r '.id'
}

grant_permissions () {
    op vault ${context} grant --vault "$vault_id" \
        --${context} "$1" \
        --permissions "$2" \
        --no-input \
        --no-color \
        --session "$session_token"
}

revoke_user () {
    op vault user revoke --vault "$vault_id" \
        --user "$1" \
        --permissions allow_viewing,allow_editing,allow_managing \
        --no-input \
        --no-color \
        --session "$session_token"
}

main () {
    # Get account password from stdin
    account_password="$(< /dev/stdin)"
    
    # Sign in and save session token
    session_token=$(echo $account_password | op signin --raw)
    
    # Exit if sign-in fails
    if [ $? -gt 0 ]
    then
        exit $?
    fi

    # Create vault with default permissions and store JSON object from output
    vault_json=$(op vault create "$VAULT_NAME" \
        --description "$VAULT_DESCRIPTION" \
        --format json \
        --no-color \
        --session "$session_token")

    # Get and store the vault UUID
    vault_id=$(extract_id_from_json "$vault_json")
    
    # Add requester permissions
    context="user" grant_permissions "$REQUESTER_EMAIL" "$REQUESTER_PERMISSIONS"
    
    # Add approving manager permissions
    context="user" grant_permissions "$MANAGER_EMAIL" "$MANAGER_PERMISSIONS"

    # Check for and save group based on name
    op_group_json=$(op group get "$GROUP_NAME" \
        --format json \
        --no-color \
        --session "$session_token")
    
    # Add group permissions
    context="group" grant_permissions "$GROUP_NAME" "$GROUP_PERMISSIONS"

    # Get signed in user details
    op_user_json=$(op user get --me \
        --format json \
        --no-color \
        --session "$session_token")

    # Get signed in user UUID
    op_user_id=$(extract_id_from_json "$op_user_json")

    # Remove vault creator from vault
    revoke_user "$op_user_id"
}

main "$@"
