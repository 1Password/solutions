#!/usr/bin/env bash
# This script will loop through all vaults the currently-logged-in user has access to. 
# For each vault, it will provide the vault name, the number of items in the vault
# the last time the vault contents were updated, and list which users and groups have access
# to the vault along with their permissions. 
op signin
for vault in $(op vault list --format=json | jq --raw-output '.[] .id')
do
        echo ""
        echo "Vault Details"
        op vault get $vault --format=json | jq -r '.|{name, items, updated_at}'
        sleep 1
        echo ""
        echo "Users"
        op vault user list $vault
        sleep 1
        echo ""
        echo "Groups"
        op vault group list $vault
        sleep 1
        echo ""
        echo "End of Vault Details"
        sleep 2
        clear
        echo ""
        echo ""
done