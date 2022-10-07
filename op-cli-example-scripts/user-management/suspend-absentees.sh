#!/usr/bin/env bash


# $(op user list --format=json | op user get - --format=json | jq -r 'select(.state == "ACTIVE")')
# How to get json into a bash array: https://blog.kellybrazil.com/2021/04/12/practical-json-at-the-command-line/

threshold=7776000 #90 days represented as seconds
# Get the date in seconds 90 days ago
# date -j -v -90d +"%s" 
current_date=$(date +"%s")



# Because bash is allergic to json, maybe best to do all the conditional
# selection in jq. 
echo $(op user list --format=json | op user get - --format=json | jq -r 'select(.state == "ACTIVE") | if (.last_auth_at | strptime("%Y-%m-%dT%H:%M:%SZ")) - "'$current_date'" > $threshold then ADD THE UUID TO AN ARRAY?  ')
# strptime("%Y-%m-%dT%H:%M:%SZ") | mktime will convert the date provided by 1Password to unix time

# suspend_list=()

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