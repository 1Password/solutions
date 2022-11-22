#!/usr/bin/env bash

# This script requires the use of the `jq` command line tool.
# You will need to install it before using this script. 
# Download `jq` from the developer: https://stedolan.github.io/jq/.


# Replace with the tag to select all items with that tag. 
# Note that if you specify multiple tags, they are separated by an "or", meaning
# an item with `tag a` OR `tag b` or both `tag a` and `tag b` will be selected . 
tag="" 

# This will write output to a file called reports.csv in the same directory as the script. 
# If you prefer a different output location, change this to the path and filename of your choosing
outputFile="report.csv"

for item in $(op item list --format=json | jq --raw-output '.[].id')
do
    op item get $item --tags $tag --format json | jq -r '{label: "Item Name", value: .title},{label: "Vault", value: .vault.name},{label: "Date Created", value: .created_at},{label: "Date Updated", value: .updated_at},.fields[] | select(.label != "Password") | [.label, .value] |@csv' >> $outputFile
    echo "" >> $outputFile
done


