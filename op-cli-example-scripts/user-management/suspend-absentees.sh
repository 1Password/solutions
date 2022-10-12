#!/usr/bin/env bash

# Store output of op only for currently-active users. 
json=$(op user list --format=json --account michaelscottpapercompany | op user get - --format=json --account michaelscottpapercompany | jq -r 'select(.state == "ACTIVE")') 

# Set threshold for max idle time
threshold=548475 # temporary value for development to ensure mix of results. Change to 7776000 for 90 days. 

# Convert threshold in seconds to number of days for use where human readability is required. 
threshold_days=$(date -j -f "%s" $threshold +"%d")

# calculate the difference between now and last_auth_at and select only those users idle for longer than $threshold
idle_users=$(echo $json | jq --argjson threshold $threshold 'if now - (.last_auth_at | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) > $threshold then .idle="true" else .idle="false" end | select(.idle == "true")')

echo 'The following users have been idle for longer than '$threshold_days' days'

# Print the UUID and name of each idle user
echo $idle_users | jq -r '.id + "   " + .name' | awk  'BEGIN { FS="\t" } { print $1, $2 }'

# Print only the UUID of each idle user
echo $idle_users | jq -r '.id + "   " + .name' | awk  '{ print $1 }' 


# At this point you could assign those UUID's to an array:
# idle_user_array=($(echo $idle_users | jq -r '.id + "   " + .name' | awk  '{ print $1 }'))
# then loop through the array with op suspend $uuid

