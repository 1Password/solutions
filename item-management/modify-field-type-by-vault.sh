#!/usr/bin/env bash
#########################################################
# MODIFY FIELD TYPE WHILE RETAINING VALUE
#########################################################
# This example shows how to change the type of a field (e.g., from
# "text" to "password") without changing the value of that field.
# This script assumes that you are modifying multiple items that have the same
# structure. In this case, this script assumes:
# - You are changing "text" field types to "password" field types
# - You are adjusting two top-level field called "Test field 1"
# - You are adjusting four fields in a section called "Example"
# - You can use the following example to generate 10 items with this 
# exact structure so you have sample data to experiment with.
# ==============================================================================
# GENERATE SAMPLE DATA 
# ==============================================================================
#
# count=0
# while [ $count -le 10 ]
# do
# 	op item create --category=login --title="my example item $count" --vault=<test vault name or UUID> \
# 	--url=https://www.1password.com --generate-password=20,letters,digits \
# 	username=scott@acme.com \
# 	'Test Field 1[text]=my test secret' \
# 	'Additional Password 1[password]=mypassword1' \
# 	'Example.Additional Password 2[text]=mypassword2' \
# 	'Example.Additional Password 3[text]=mypassword3' \
# 	'Example.Additional Password 4[text]=mypassword4' \
# 	'Example.Additional Password 5[text]=mypassword5'
# 	((count++))
# done
# 
# ==============================================================================
# CHANGE FIELD TYPE IN SAMPLE DATA
# ==============================================================================
# This script will change all custom text fields to password fields in the sample data created above. 
# The value stored in the field will remain unchanged. This example will change all items in a vault
# however you could alternatively select items by tag, name, or UUID instead. 

vaultUUID=<vault name or UUID>
for item in $(op item list --vault $vaultUUID --format=json | jq --raw-output '.[].id')
do
	op item edit $item 'Test Field 1[password]' \
	'Example.Additional Password 2[password]' \
	'Example.Additional Password 3[password]' \
	'Example.Additional Password 4[password]' \
	'Example.Additional Password 5[password]'
done