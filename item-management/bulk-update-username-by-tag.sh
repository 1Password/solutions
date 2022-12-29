#!/usr/bin/env bash
#########################################################
# MODIFY USERNAME FIELD FOR ALL ITEMS WITH SPECIFIED TAG
#########################################################
# This script replaces or adds the value of the website field for all items with
# specified tags.
# Note that if you specify multiple tags, they are separated by an "or", meaning
# an item with `tag a` OR `tag b` or both `tag a` and `tag b` will be selected . 

tags="one,or,more,tags"
newUsername="username"


for item in $(op item list --tags $tags --format=json | jq --raw-output '.[].id')
do
	op item edit $item username=$newUsername
done