#!/usr/bin/env bash


vault_list=()
while IFS= read -r line; do
    op vault create $line | tee | grep ID: | sed 's/ID:                   //g' >> created
done < <(tail -n +2 vaultlist | sort -u) # vaultlist can be substituted with path/to/file if you prefer a different input file. 