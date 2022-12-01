#!/usr/bin/env bash

# This script will change the prefix on all groups that contain the specified prefix. 
# Adjust the values as desired on the line indicated by comments below. 
# This script will not change the name of any built-in groups (e.g., "Administrators" or "Owners")


groups=$(op group list | awk 'NR>1 { print $1 }')
for group in $groups
do
    name=$(op group get $group --format json | jq -r .name)
    echo $name
    # OLD is the prefix to be removed. NEW is the prefix to be added. 
    # Leave the ^ character to ensure the substitution only applies to the prefix rather than another part of the name
	name=$(echo $name | sed 's/^OLD/NEW/g')  
	echo $name
    op group edit $group --name="$name"
done
