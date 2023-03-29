#!/usr/bin/env python3

# This script will create vaults and login items from a LastPass export
# generated through their web-based exported or the lpass CLI (this has not
# been tested on exports from their browser extension or other methods).
# Shared/Nested folders in 1Password will have separate, non-nested
# vaults created. Items not belonging to any shared folder will be created
# in the user's Private vault.
#
# Credit to @jbsoliman for the original script and @svens-uk for many significant enhancements

import csv
import json
import subprocess
import sys

from utils import normalize_vault_name
from template_generator import LPassData, TemplateGenerator


def fetch_personal_vault():
    # Get the Private or Personal vault
    # The one listed first should be the correct one
    try:
        vault_list_command_output = subprocess.run([
            "op", "vault", "list",
            "--format=json"
        ], check=True, capture_output=True)
    except:
        sys.exit("An error occurred when attempting to fetch your 1Password vaults.")

    vault_list = json.loads(vault_list_command_output.stdout)
    personal_vault = next(filter(lambda x: (x["name"] == "Private" or x["name"] == "Personal"), vault_list), None)

    if personal_vault is None:
        sys.exit("Couldn't find your Personal or Private vault.")

    return personal_vault


def create_item(vault: str, template):
    # Create item
    subprocess.run([
        "op", "item", "create", "-", f"--vault={vault}"
    ], input=template, text=True, stdout=subprocess.DEVNULL)


def migrate_items(csv_data, options):
    created_vault_list = {}
    is_csv_from_web_exporter = False
    personal_vault = fetch_personal_vault()
    stats = {
        'total': 0,
        'migrated': 0,
        'skipped': 0,
        'vaults': 0,
    }

    linereader = csv.reader(csv_data, delimiter=',', quotechar='"')
    heading = next(linereader)
    if 'totp' in heading:
        is_csv_from_web_exporter = True

    for row in linereader:
        if len(row) == 0:
            continue

        stats['total'] += 1
        if is_csv_from_web_exporter:
            url = row[0]
            username = row[1]
            password = row[2]
            otp_secret = row[3]
            notes = row[4]
            title = row[5]
            vault = row[6]
        else:
            url = row[0]
            username = row[1]
            password = row[2]
            notes = row[3]
            title = row[4]
            vault = row[5]
            otp_secret = None

        if vault.startswith("Shared") and options['ignore-shared']:
            print(f"\t\"{title}\" => skipped (ignore shared credentials)")
            stats['skipped'] += 1
            continue

        # Check if vault is defined
        vault_defined = vault and vault != ""
        # Create vault, if needed
        if vault_defined and vault not in created_vault_list:
            if not options['dry-run']:
                try:
                    normalized_vault_name = normalize_vault_name(vault)
                    vault_create_command_output = subprocess.run([
                        "op", "vault", "create",
                        normalized_vault_name,
                        "--format=json"
                    ], check=True, capture_output=True)
                except:
                    print(f"\t\"{vault}\" => failed to create new vault \"{normalized_vault_name}\"")
                    continue
                new_vault_uuid = json.loads(vault_create_command_output.stdout)["id"]
                created_vault_list[vault] = new_vault_uuid
                stats["vaults"] += 1
                print(f"\t\"{vault}\" => created new vault \"{normalized_vault_name}\"")
            else: 
                normalized_vault_name = normalize_vault_name(vault)
                created_vault_list[vault] = vault
                print(f"\tVault \"{vault}\" => would be created as \"{normalized_vault_name}\"; skipped (dry run)")
                
        template = TemplateGenerator(LPassData(
            url=url,
            username=username,
            password=password,
            otp_secret=otp_secret,
            notes=notes,
            title=title,
            vault=vault,
        )).generate()

        if not template:
            print(f"\t\"{title}\" => skipped (incompatible item)")
            stats["skipped"] += 1
            continue

        json_template = json.dumps(template)
        if not options['dry-run']:
            vault_to_use = created_vault_list[vault] if vault_defined else personal_vault['id']

        if options['dry-run']:
            print(f"\tCreating item \"{title}\" => skipped (dry run)")
            continue

        create_item(vault_to_use, json_template)
        stats["migrated"] += 1
        print(f"\t\"{title}\" => migrated")

    print(f"\nMigration complete!\nTotal {stats['total']} credentials.\nMigrated {stats['migrated']} credentials.\nCreated {stats['vaults']} vaults.\nSkipped {stats['skipped']} credentials.")
