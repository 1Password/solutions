#!/usr/bin/env python3

# This script will create 1Password vaults from each unique value
# in the `grouping` column of a LastPass export generated through their
# web-based exported or the lpass CLI (this has not
# been tested on exports from their browser extension or other methods).
# Shared/Nested folders in 1Password will have separate, non-nested
# vaults created.
#
# This script does NOT create items in 1Password.
import csv
import json
import subprocess


def migrate_folders(csv_data):
    created_vault_list = {}
    linereader = csv.reader(csv_data, delimiter=',', quotechar='"')
    next(linereader)  # skip csv header row
    lp_folder_list = set()

    for row in linereader:
        vault = row[6]
        lp_folder_list.add(vault)

    for folder in lp_folder_list:
        if folder and folder not in created_vault_list:
            try:
                vault_create_command_output = subprocess.run([
                    "op", "vault", "create",
                    folder,
                    "--format=json"
                ], check=True, capture_output=True)
            except:
                print(f"A vault with name {vault} could not be created.")
                continue
            new_vault_uuid = json.loads(vault_create_command_output.stdout)["id"]
            created_vault_list[folder] = new_vault_uuid
    print(f"The following 1Password vaults were created:")
    print("\n".join(created_vault_list))
