#!/usr/bin/env bash
# This script helps identify members of your 1Password account who may not have unlocked 1Password
# in a while. You may want to reach out to these people or perform a bulk action on them, 
# such as adjusting their permissions or access using the CLI
#
# The script prompts you for the number of days after which point you deem a user to be "idle" and 
# will list all users who have not unlocked 1Password in that time. 

read threshold_days\?"After how many days is someone idle? "

# Store output of op only for currently-active users. 
# json=$(op user list --format=json | op user get - --format=json | jq -r 'select(.state == "ACTIVE")') 

echo " "
echo "Great, we'll find users who have not signed into 1Password in $threshold_days days"
echo " "
# Set threshold for max idle time Change to 7776000 for 90 days
threshold=$((threshold_days * 86400))

# calculate the difference between now and last_auth_at and select only those users idle for longer than $threshold
idle_users=$(echo $json | jq --argjson threshold $threshold 'if now - (.last_auth_at | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) > $threshold then .idle="true" else .idle="false" end | select(.idle == "true")')

echo 'The following users have been idle for longer than '$threshold_days' days or '$threshold' seconds'

# Print the UUID, name, email, and last authentication date of each idle user.
# Currently outputting all fields with tabs. Adjust order and separater as desired with awk 
echo $idle_users | jq -r '.id + "\t" + .name + "\t" + .email + "\t" + .last_auth_at'

# ====================================================================
# Some other printing options
# ====================================================================
# Print only the UUID of each idle user
# echo $idle_users | jq -r '.id'
# 
# Print only the email of each idle user
# echo $idle_users | jq -r '.email'
# 
# ====================================================================
# Next steps:
# ====================================================================
# At this point you can leverage this information for a few purposes:
# - Use the list of email addresses to send reminders or check in about problems they may have
# - Track usage changes over time
# - Perform bulk actions on the list of users in a for loop by creating an array of UUID's and looping through it:
# idle_user_array=($(echo $idle_users | jq -r '.id')) 
# for user in $idle_user_array 
# do
#   op some action
# done
# ====================================================================
