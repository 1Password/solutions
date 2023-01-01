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
# Note: Currently TOTP secrets are not migrated. 
# Credit to @jbsoliman

import csv, subprocess
vault_list = []
with open('export.csv', newline='') as csvfile:
    linereader = csv.reader(csvfile, delimiter=',', quotechar='"')
    next(linereader)
    
    for row in linereader:
        url = row[0]
        username = row[1]
        password = row[2]
        notes= row[4]
        title = row[5]        
        vault = row[6]
        
        # omitting Secure Notes
        if url == "http://sn":
            continue
        
        if not vault or vault == "":
            subprocess.run(["op", "item", "create",
                 "--vault=Private",
                f"--tags={vault}",
                 "--category=login",
                f"--title={title}",
                f"--url={url}",
                f"username={username}",
                f"password={password}",
                f"notes={notes}"
            ])
            continue

        if vault not in vault_list:
            vault_list.append(vault) 
            # create vault
            subprocess.run(["op", "vault", "create", vault])
            # create item
            subprocess.run(["op", "item", "create",
                f"--vault={vault}",
                f"--tags={vault}",
                 "--category=login",
                f"--title={title}",
                f"--url={url}",
                f"username={username}",
                f"password={password}",
                f"notes={notes}"
            ])
            continue

        if vault in vault_list:
            # create item
            subprocess.run(["op", "item", "create",
                f"--vault={vault}",
                f"--tags={vault}",
                 "--category=login",
                f"--title={title}",
                f"--url={url}",
                f"username={username}",
                f"password={password}",
                f"notes={notes}"
            ])
            continue
        
        