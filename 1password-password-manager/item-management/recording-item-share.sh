#!/usr/bin/env bash

#This script help you automate the creation of a 1Password Item to use for an item-sharing link for the emails provided in the prompts
#The script cleans up the 1Password item after generating the share-item link.

#set the Role for the Item Title, e.g. 1Password Solutions Architect
role="1Password Solutions Architect"

op signin

echo "Enter the customer organization name:"
read company

#creates Item Title based off company name
itemTitle="${company} + ${role} - Zoom Recording"

#takes multi-line input of typical zoom link copy
echo -e "\033[0;31mEnter the copied share link from Zoom\033[0m"
echo -e "\033[0;32mUse the Enter key twice to exit the input\033[0m"
zoomPaste=$(sed '/^$/q')
stringarray=($zoomPaste)
zoomURL=${stringarray[0]}
zoomPC=${stringarray[2]}

#creates new item for sharing
op item create --vault private --category=login --title="${itemTitle}" --url="${zoomURL}" password="${zoomPC}" notes="This recording will only be accessible for 7 days."

#Create item share link to send out to the customer
echo -e "\033[0;31mEnter the customer email address(es), comma seperated:\033[0m"
read emailadd
echo ""
echo "Generating a Share Item link for" "$emailadd" "to access:" "$itemTitle"
op item share "$itemTitle" --vault Private --emails $emailadd --expiry 168h

echo -e "\033[0;32mCopy the link above and share this link with ${emailsadd}\033[0m"

#deletes created item to clean up vault. (remove the archive flag if you want to fully delete the item)
op item delete "$itemTitle" --vault Private --archive
