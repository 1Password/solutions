#!/usr/bin/env bash

vault_IDs=($(op vault list --format=json | jq --raw-output '.[] .id'))

for vault in $vault_IDs 
do
    echo "outer loop"
    for group in $(op group list --vault $vault --format=json | jq --raw-output '.[] .id') 
    do
        echo "inner loop"
        op vault group revoke \
	    --permissions export_items \
	    --group $group \
	    --vault $vault
    done
done


