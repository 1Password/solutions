#!/usr/bin/env bash

# This script will remove or grant the specified group from having the defined permission from all vaults. 
# Adjust the values as desired on the line indicated by comments below. 
#
# You may see "the accessor doesn't have any permissions" errors at times while running this script.
# This means the group being acted on at that moment did not have the permission being revoked. 
# This error can be ignored. 
#
# This script requires `jq` is installed on your system. See: https://stedolan.github.io/jq/ for installation instructions.

#This can be altered to use the `grant` command to add the permission or the `revoke` command can be used to remove the permission. 
opaction=revoke

#change the name of the group to match the desired group from your account or the group UUID.
group=testgroup

#change the permission below (comma seperated) of the permissions (you can check the permissions available here: 
# https://developer.1password.com/docs/cli/reference/management-commands/vault#vault-group-revoke) you want to apply to match the desired group from your account.
permission=manage_vault

vault_IDs=$(op vault list --format=json | jq --raw-output '.[] .id')

for vault in $vault_IDs 
do
    op vault group $opaction --vault ${vault} --group ${group} --permissions ${permission}
done