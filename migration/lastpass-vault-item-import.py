#!/usr/bin/env python3

# This script will create vaults and login items from a LastPass export 
# generated through their web-based exported or the lpass CLI (this has not 
# been tested on exports from their browser extension or other methods). 
# Shared/Nested folders in 1Password will have separate, non-nested 
# vaults created. Items not belonging to any shared folder will be created 
# in the user's Private vault.
# The script expects your export to reside in the same directory as 
# the script with the name export.csv. 
# 
# Credit to @jbsoliman

import csv, json, subprocess, sys

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
p_vault = next(filter(lambda x: (x["name"] == "Private" or x["name"] == "Personal"), vault_list), None)
if p_vault is None:
    sys.exit("Couldn't find your Personal or Private vault.")

p_vault_uuid = p_vault["id"]

created_vault_list = {}

# Read LastPass export
with open('export.csv', newline='') as csvfile:
    linereader = csv.reader(csvfile, delimiter=',', quotechar='"')
    next(linereader)
    
    for row in linereader:
        url = row[0]
        username = row[1]
        password = row[2]
        otp_secret = row[3]
        notes = row[4]
        title = row[5]        
        vault = row[6]

        # Omitting Secure Notes
        if url == "http://sn":
            continue

        # Account for empty fields
        if not url:
            url = "no URL"
        if not title:
            title = "Untitled Login"

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
                print(f"Failed to create vault for folder {vault}. Item \"{title}\" on line {linereader.line_num} not migrated.")
                continue
            new_vault_uuid = json.loads(vault_create_command_output.stdout)["id"]
            created_vault_list[vault] = new_vault_uuid
        
        # Create item template
        login_template["title"] = title
        login_template["urls"] = [
            {
                "label": "website",
                "primary": True,
                "href": url
            }
        ]
        login_template["tags"] = [vault if vault_defined else p_vault['name']]
        login_template["fields"] = [
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

        json_login_template = json.dumps(login_template)
        
        # Create item
        subprocess.run([
            "op", "item", "create", "-",
            f"--vault={created_vault_list[vault] if vault_defined else p_vault_uuid }"
        ], input=json_login_template, text=True)