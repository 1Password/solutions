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
from secure_note_transformer import LPassData, SecureNoteTransformer


def fetch_login_item_template():
    # Fetch the login item template, and compare to what's expected
    expected_login_template = {
      "title": "",
      "category": "LOGIN",
      "fields": [
        {
          "id": "username",
          "type": "STRING",
          "purpose": "USERNAME",
          "label": "username",
          "value": ""
        },
        {
          "id": "password",
          "type": "CONCEALED",
          "purpose": "PASSWORD",
          "label": "password",
          "password_details": {
            "strength": "TERRIBLE"
          },
          "value": ""
        },
        {
          "id": "notesPlain",
          "type": "STRING",
          "purpose": "NOTES",
          "label": "notesPlain",
          "value": ""
        }
      ]
    }
    try:
        login_template_command_output = subprocess.run([
            "op", "item", "template", "get", "login",
            "--format=json"
        ], check=True, capture_output=True)
    except:
        sys.exit("An error occurred when attempting to fetch the login item template.")

    login_template = json.loads(login_template_command_output.stdout)
    if expected_login_template != login_template:
        # If the template doesn't match, then CLI behaviour may have changed.
        # In this case, the script should be updated with the new template.
        sys.exit("The login template returned by the CLI does not match the expected login template.\n\nThis script may be designed for an older version of the CLI.")

    return login_template


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


def count_credentials_to_migrate(csv_data):
    linereader = csv.reader(csv_data, delimiter=',', quotechar='"')
    next(linereader) # skip header row from counting
    credentials_amount = sum(1 for _ in linereader)
    print(f"Found {credentials_amount} credentials to migrate:")
    return credentials_amount


def migrate_items(csv_data):
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

        vault = normalize_vault_name(vault)
        # Check if vault is defined
        vault_defined = vault and vault != ""
        # Create vault, if needed
        if vault_defined and vault not in created_vault_list:
            try:
                vault_create_command_output = subprocess.run([
                    "op", "vault", "create",
                    vault,
                    "--format=json"
                ], check=True, capture_output=True)
            except:
                print(f"\t\"{vault}\" => failed to create new vault \"{vault}\"")
                continue
            new_vault_uuid = json.loads(vault_create_command_output.stdout)["id"]
            created_vault_list[vault] = new_vault_uuid
            stats["vaults"] += 1
            print(f"\t\"{vault}\" => created new vault \"{vault}\"")

        # Generate template from lpass Secure Notes
        if url == "http://sn":
            template = SecureNoteTransformer(LPassData(
                url=url,
                username=username,
                password=password,
                otp_secret=otp_secret,
                notes=notes,
                title=title,
                vault=vault,
            )).transform()
        else:
            # Generate Login template
            # Account for empty fields
            if not url:
                url = "no URL"
            if not title:
                title = "Untitled Login"

            # Create item template
            template = fetch_login_item_template()
            template["title"] = title
            template["urls"] = [
                {
                    "label": "website",
                    "primary": True,
                    "href": url
                }
            ]
            template["tags"] = [vault if vault_defined else personal_vault['name'], "LastPass"]
            template["fields"] = [
                {
                    "id": "username",
                    "type": "STRING",
                    "purpose": "USERNAME",
                    "label": "username",
                    "value": username
                },
                {
                    "id": "password",
                    "type": "CONCEALED",
                    "purpose": "PASSWORD",
                    "label": "password",
                    "password_details": {
                        "strength": "TERRIBLE"
                    },
                    "value": password
                },
                {
                    "id": "notesPlain",
                    "type": "STRING",
                    "purpose": "NOTES",
                    "label": "notesPlain",
                    "value": notes
                }
            ] + ([{
                "id": "one-time password",
                "type": "OTP",
                "label": "one-time password",
                "value": otp_secret
            }] if otp_secret else [])

        if not template:
            print(f"\t\"{title}\" => skipped (incompatible item)")
            stats["skipped"] += 1
            continue

        json_template = json.dumps(template)
        vault_to_use = created_vault_list[vault] if vault_defined else personal_vault['id']
        create_item(vault_to_use, json_template)
        stats["migrated"] += 1
        print(f"\t\"{title}\" => migrated")
    
    print(f"\nMigration complete! Total {stats['total']} credentials. Migrated {stats['migrated']} credentials, created {stats['vaults']} vaults, skipped {stats['skipped']} credentials.")
