#!/usr/bin/env bash

# Store output of op only for currently-active users. 
json=$(op user list --format=json --account michaelscottpapercompany | op user get - --format=json --account michaelscottpapercompany | jq -r 'select(.state == "ACTIVE")') 

# Get the date in seconds 90 days ago
# date -j -v -90d +"%s" 
current_date=$(date +"%s")

# Set threshold for max idle time
# threshold=7776000 #90 days represented as seconds
threshold=548475 # temporary value for development to ensure mix of results. 
threshold_days=$(date -j -f "%s" $threshold +"%d")

# calculate the difference between now and last_auth_at

idle_users=$(echo $json | jq --argjson threshold $threshold 'if now - (.last_auth_at | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) > $threshold then .idle="true" else .idle="false" end | select(.idle == "true")')

echo $idle_users | jq 'length' | wc -l

echo 'The following users have been idle for longer than '$threshold_days' days'
echo $idle_users | jq -r '.id " " .name'
# The stuff below here is all just scraps 

# How to get json into a bash array: https://blog.kellybrazil.com/2021/04/12/practical-json-at-the-command-line/
# Because bash is allergic to json, maybe best to do all the conditional
# selection in jq. 

# One approach might be to actually do it in two steps: calculate a new idleTime:seconds k:v pair that is appended to the json, 
# then in a second step, iterate through the json to find objects with idleTime > threshold. 

echo $(op user list --format=json | op user get - --format=json | jq -r 'select(.state == "ACTIVE") | if (.last_auth_at | strptime("%Y-%m-%dT%H:%M:%SZ")) - "'$current_date'" > $threshold then [ADD,THE,UUID,TO,AN,ARRAY?]  ')
# strptime("%Y-%m-%dT%H:%M:%SZ") | mktime will convert the date provided by 1Password to unix time

echo $json | jq 'if .last_auth_at | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime - todate > env.threshold then .name else "active"'




for user in $all_users
    do
        user_last_auth=$(echo $user | jq -r '.last_auth_at')
        echo "user last auth:  $user_last_auth"
        seconds  date -j -f "%F" echo $user_last_auth | sed -E 's/(T..:..:...)//g' +"%s"
        echo "seconds:  $seconds"
    done


for user in $all_users
do
    echo $user | jq
done

for user in $all_users 
do
    echo $(echo $user | jq -r '[].last_auth_at')
done