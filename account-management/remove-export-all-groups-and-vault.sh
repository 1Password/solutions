#!/usr/bin/env bash

# This script removes the Export permission for ALL VAULTS that EVERY group has access to. 
# This includes the Owners and Administrators groups. 
#
# This script must be run using a 1Password account in the Owners group, otherwise it may fail to adjust
# permissions for vaults the account does not have "manage vault" permission on. 
#
# You may see "the accessor doesn't have any permissions" errors at times while running this script.
# This means the group being acted on at that moment did not have the permission being revoked. 
# This error can be ignored. 
#
# This script requires `jq` is installed on your system. See: https://stedolan.github.io/jq/ for installation instructions.

vault_IDs=($(op vault list --format=json | jq --raw-output '.[] .id'))

for vault in $vault_IDs 
do
    for group in $(op group list --vault $vault --format=json | jq --raw-output '.[] .id') 
    do
        op vault group revoke \
	    --permissions export_items \
	    --group $group \
	    --vault $vault
    done
done


