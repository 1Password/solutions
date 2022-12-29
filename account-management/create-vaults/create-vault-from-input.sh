#!/usr/bin/env bash
########################
# CREATE VAULTS FROM INPUT LIST
########################
# This script takes a line-delimited list of strings and creates a 1Password
# vault for each line. This is especially handy if you have a list of folders
# or vaults from another password management solution you'd like to recreate
# in 1Password. 
#
# The script will also create a file called "created" with the UUIDs of the 
# newly-created vaults, making it easy to further manipulate those vaults
# using the 1Password CLI, if desired. For example, if your script didn't 
# provide expected results, you can use the included deletion script to delete
# the newly created vaults, adjust the script, and run it again. 
#
########################
# LASTPASS MIGRATORS
########################
# For example, if you are migrating from LastPass, you can use the "grouping" 
# column provided in the LastPass export as your input list. This script
# is designed to omit the first line (the heading "grouping") and de-duplicate
# the list prior to creating vaults. 
# As a result, simply copy and pasting the Grouping column into a text file
# is sufficient all that is required prior to running this script. 
# The vaultlist file included with this script is an example of copy and pasting
# the Grouping column. 
#
# NOTE the first line fed to the script is a blank line and will produce an 
# error you can safely ignore. 

while IFS= read -r line; do
    op vault create $line | grep ID: | sed 's/ID:                   //g' >> created
done < <(tail -n +2 vaultlist | sort -u) # vaultlist can be substituted with path/to/file if you prefer a different input file. 


# To delete the vaults created by this script, use the following:
# for vault in $(cat created) do
#     op vault delete $vault
# done