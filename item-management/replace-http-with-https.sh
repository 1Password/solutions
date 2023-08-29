#!/usr/bin/env bash
#########################################################
# REPLACE HTTP WITH HTTPS 
#########################################################
# This script replaces or adds the value of the website field for all items in a specified vault

#Provide a vault UUID or vault name
vaultUUID=""

# add new url to each item
for item in $(op item list --vault $vaultUUID --format=json | jq --raw-output '.[].id')
do
	oldURL=$(op item get $item --format=json | jq --raw-output '.urls[].href')
	newURL=$(echo $oldURL | sed 's/^http:\/\//https:\/\//g')
	op item edit $item website=$newURL
done