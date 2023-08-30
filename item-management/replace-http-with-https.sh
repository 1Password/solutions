#!/usr/bin/env bash
#########################################################
# REPLACE HTTP WITH HTTPS 
#########################################################
# This script will replace "http" with "https" for the 
# website field of all Login items in the specified vault 

#Provide a vault UUID or vault name
vaultUUID=""

# add new url to each item
for item in $(op item list --vault $vaultUUID --categories Login --format json | jq --raw-output '.[].id')
do
	oldURL=$(op item get $item --format=json | jq --raw-output '.urls[].href')
	newURL=$(echo $oldURL | sed 's/^http:\/\//https:\/\//g')
	op item edit $item website=$newURL
done