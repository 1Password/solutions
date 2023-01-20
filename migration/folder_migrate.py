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

from utils import normalize_vault_name


def migrate_folders(csv_data, options):
    created_vault_list = {}
    lp_folder_list = set()
    is_csv_from_web_exporter = False
    stats = {
        'total': 0,
        'migrated': 0,
        'skipped': 0,
    }

    linereader = csv.reader(csv_data, delimiter=',', quotechar='"')
    heading = next(linereader)

    if 'totp' in heading:
        is_csv_from_web_exporter = True

    for row in linereader:
        vault_name = row[6] if is_csv_from_web_exporter else row[5]
        if vault_name.startswith("Shared") and options['ignore-shared']:
            print(f"\t\"{vault_name}\" => skipped (ignore shared folders)")
            stats["skipped"] += 1
            continue

        if vault_name:
            lp_folder_list.add(normalize_vault_name(vault_name))

    stats['total'] = len(lp_folder_list)
    for folder in lp_folder_list:
        try:
            vault_create_command_output = subprocess.run([
                "op", "vault", "create",
                folder,
                "--format=json"
            ], check=True, capture_output=True)
        except:
            print(f"\t\"{folder}\" => skipped (cannot be created)")
            stats["skipped"] += 1

            continue
        new_vault_uuid = json.loads(vault_create_command_output.stdout)["id"]
        created_vault_list[folder] = new_vault_uuid
        print(f"\t\"{folder}\" => created")
        stats["migrated"] += 1

    print(f"\nFolders migration complete! Total {stats['total']} folders. Created {stats['migrated']} vaults, skipped {stats['skipped']}.")
