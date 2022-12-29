#!/usr/bin/env bash

# ==============================================================================
# Deprovision users from a csv input list
# ==============================================================================

# this script will ingest a .csv file containing names and email addresses and 
# invite each person to join the currently-logged in 1Password account. 
#
# Please note that your input file must end with an empty line, otherwise the 
# last person in the file will be skipped. 
#
# This script should accommodate most names and email addresses. If a person's 
# double quotes ("), they will be changed to single quotes ('). 

# Set input data
input_file=people.csv

# Invite each user in the input file
while IFS="," read input_name input_email # modify IFS= to conform with your csv seperator.
do
	op user provision --name="$input_name" --email="$input_email"
done < <(sed "s/\"/'/g" <(tail $input_file)) # If there's a header in your csv, change to <(tail -n +2 $input_file)



# ==============================================================================
# Deprovision users from the same list 
# WARNING: Deleted users and their Private vaults are irrecoverable.
# ==============================================================================
# while IFS="," read input_name input_email # modify IFS= to conform with your csv seperator.
# do
# 	op user delete "$input_email"
# done < <(sed "s/\"/'/g" <(tail $input_file)) # If there's a header in your csv, change to <(tail -n +2 $input_file)