#!/usr/bin/env bash

# Get a list of vaults the user has access to. 
# Note that this does not include vaults the user had access to
# by virtue of their group membership. 

# Prompt person running script for UUID of target user. 
read target_uuid\?"What is the UUID of the user? "

# Output basic information about the target user
echo "Getting access information for " $target_uuid
echo " "
op user get $target_uuid
echo " "

# Get details for each vault the target user has access to
for vault in $(op vault list --user $target_uuid --format=json | jq -r '.[] .id')
    do
        op vault user list $vault --format=json | jq '.[] | select(.id == "'$target_uuid'")'
    done
