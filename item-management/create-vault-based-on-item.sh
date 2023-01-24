#!/usr/bin/env bash
# This script will loop through vault specied in the vaultUUID variable. 
# For each item in this vault, it will create (without administrator group management permissions) 
# a new vault based off the name in the fieldvalue variable. 
# This could be a custom field such as "Company" in all the items in the vault being looped through.
# The original item, is then created in the new vault and removed from the original vault.

# This script was inspired by a use case where 1Password Connect is tied to a "landing" vault where new items 
# are being created through a web form for new clients/companies in this landing vault, where the new items
# are only stored until they are moved to a specific vault for the client/company.

#Change this value to the vault that you are moving items from, your landing vault.
vaultUUID=<some vault UUID>

#Change the value of this to match the corresponding field you are looking in the item in this landing vault.
fieldvalue=Company

# creates new vault based of item detail from field from variable `fieldvalue` specified above. 
# The field must be valid for the specified vault.
for item in $(op item list --vault $vaultUUID --format=json | jq --raw-output '.[].id')
do
    vaultname=`op item get $item --fields $fieldvalue`
    op vault create $vaultname --allow-admins-to-manage false
    op item get $item --format json | op item create --vault $vaultname
    op item delete $item --archive --vault $vaultUUID
done