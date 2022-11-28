#!/usr/bin/env bash

# This script will change the prefix on all groups that contain the specified prefix. 
# Adjust the values as desired on the line indicated by comments below. 
# This script will not change the name of any built-in groups (e.g., "Administrators" or "Owners")
# This script will indescriminately match the start of the group name. This means if you have a group
# Called "ONTARIO" and are replacing the prefix "ON_" for groups like "ON_all staff" and "ON_Human Resources"
# you may see some onwanted substitutions. Group names are printed before and after transformation so you can identify
# any mis-transformed names, 

groups=$(op group list | awk 'NR>1 { print $1 }')
for group in $groups
do
    name=$(op group get $group --format json | jq -r .name)
    echo $name
    # OLD is the prefix to be removed. NEW is the prefix to be added. 
    # Leave the ^ character to ensure the substitution only applies to the prefix rather than another part of the na,e
	name=$(echo $name | sed 's/^OLD/NEW/g')  
	echo $name
    op group edit $group --name="$name"
done
