#!/usr/bin/env bash

# This script will create items based on a whitespace-delimited input file. 


# Set the name or UUID of the vault in which the new items should be created. 
vault=""

title=($(awk '{ print $1 }' ./db-list.txt))
username=($(awk '{ print $2 }' ./db-list.txt))
item_name=($(awk '{ print $3 }' ./db-list.txt))

count=1
while [ $count -le ${#ip[@]} ]
do

	op item create --vault=$vault \
	--tags="devLocal" \
	--category=login \
	--url=${title[$count]} \
	--title=${item_name[$count]} \
	username=${username[$count]} \
	--generate-password=32,letters,digits

	((count++))

done
