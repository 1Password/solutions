#!/usr/bin/env bash

#########################################################
# MODIFY WEBSITE FIELD FOR ALL ITEMS IN A VAULT
#########################################################
# This script replaces or adds the value of the website field for all items in a specified vault

vaultUUID=<some vault UUID>
newURL='https://example.com'

# add new url to each item
for item in $(op item list --vault $vaultUUID --format=json | jq --raw-output '.[].id')
do
	op item edit $item website=$newURL
done