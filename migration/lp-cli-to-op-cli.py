#!/usr/bin/env python3

import csv, json, subprocess, sys

vault_list = {}

# Get LastPass export data 

def get_lp_data():
    # Sign user into LastPass
    lp_username = input("Please enter your LastPass username ")
    try:
        subprocess.run(["lpass","login",lp_username])
    except:
        sys.exit("Unable to sign into LastPass")

    # Issue export command to lpass
    try:
        lp_export = subprocess.run(["lpass", "export"], text=True, capture_output=True).stdout
    except:
        sys.exit("Unable to retrieve LastPass data. Ensure you have signed into LastPass using ")
    return lp_export

lp_data = get_lp_data()

linereader = csv.reader(lp_data, delimiter=',', quotechar='"')
next(linereader)

for row in linereader:
    for row in linereader:
        url = row[0]
        username = row[1]
        password = row[2]
        otp_secret = row[3]
        notes= row[4]
        title = row[5]        
        vault = row[6]

        print("url: ", url)


# # Get the Private or Personal vault
# # The one listed first should be the correct one
# vault_list_command_output=None
# try:
#     vault_list_command_output = subprocess.run([
#         "op", "vault", "list",
#         "--format=json"
#     ], check=True, capture_output=True)
# except:
#     sys.exit("An error occurred when attempting to fetch your 1Password vaults.")

# vault_list = json.loads(vault_list_command_output.stdout)
# p_vault = next(filter(lambda x: (x["name"] == "Private" or x["name"] == "Personal"), vault_list), None)
# if p_vault is None:
#     sys.exit("Couldn't find your Personal or Private vault.")

# p_vault_uuid = p_vault["id"]

# created_vault_list = {}

# # Read LastPass export
# with open('export.csv', newline='') as csvfile:
#     linereader = csv.reader(csvfile, delimiter=',', quotechar='"')
#     next(linereader)
    
#     for row in linereader:
#         url = row[0]
#         username = row[1]
#         password = row[2]
#         otp_secret = row[3]
#         notes= row[4]
#         title = row[5]        
#         vault = row[6]
        
#         # Omitting Secure Notes
#         if url == "http://sn":
#             continue

#         # Setup for OTP 
#         if otp_secret:
#             otp_secret_create = "one-time-password[otp]=%s" % otp_secret
#         else: 
#             otp_secret_create = ""

#         # Account for empty fields
#         if not url:
#             url = "no URL"
#         if not title:
#             title = "Untitled Login"
        
#         # Create item in Private/Personal vault
#         if not vault or vault == "":
#             if otp_secret_create:
#                 subprocess.run([
#                     "op", "item", "create",
#                     f"--vault={p_vault_uuid}",
#                     f"--tags={vault}",
#                     "--category=login",
#                     f"--title={title}",
#                     f"--url={url}",
#                     f"{otp_secret_create}",
#                     f"username={username}",
#                     f"password={password}",
#                     f"notes={notes}"
#                 ])
#             else:
#                 subprocess.run([
#                     "op", "item", "create",
#                     f"--vault={p_vault_uuid}",
#                     f"--tags={vault}",
#                     "--category=login",
#                     f"--title={title}",
#                     f"--url={url}",
#                     f"username={username}",
#                     f"password={password}",
#                     f"notes={notes}"
#                 ])
#             continue

#         # Create vault, if needed, and item
#         if vault not in created_vault_list:
#             vault_create_command_output = None
#             # create vault
#             try:
#                 vault_create_command_output = subprocess.run([
#                     "op", "vault", "create",
#                     vault,
#                     "--format=json"
#                 ], check=True, capture_output=True)
#             except:
#                 print(f"Failed to create vault for folder {vault}. Item \"{title}\" on line {linereader.line_num} not migrated.")
#                 continue
#             new_vault_uuid = json.loads(vault_create_command_output.stdout)["id"]
#             created_vault_list[vault] = new_vault_uuid
            
#             # create item
#             if otp_secret_create:
#                 subprocess.run([
#                     "op", "item", "create",
#                     f"--vault={created_vault_list[vault]}",
#                     f"--tags={vault}",
#                     "--category=login",
#                     f"--title={title}",
#                     f"--url={url}",
#                     f"{otp_secret_create}",
#                     f"username={username}",
#                     f"password={password}",
#                     f"notes={notes}"
#                 ])
#             else:
#                 subprocess.run([
#                     "op", "item", "create",
#                     f"--vault={created_vault_list[vault]}",
#                     f"--tags={vault}",
#                     "--category=login",
#                     f"--title={title}",
#                     f"--url={url}",
#                     f"username={username}",
#                     f"password={password}",
#                     f"notes={notes}"
#                 ])
#             continue
        
#         # Create item in extant vault
#         if vault in created_vault_list:
#             # create item
#             if otp_secret_create:
#                 subprocess.run([
#                     "op", "item", "create",
#                     f"--vault={created_vault_list[vault]}",
#                     f"--tags={vault}",
#                     "--category=login",
#                     f"--title={title}",
#                     f"--url={url}",
#                     f"{otp_secret_create}",
#                     f"username={username}",
#                     f"password={password}",
#                     f"notes={notes}"
#                 ])        
#             else: 
#                 subprocess.run([
#                     "op", "item", "create",
#                     f"--vault={created_vault_list[vault]}",
#                     f"--tags={vault}",
#                     "--category=login",
#                     f"--title={title}",
#                     f"--url={url}",
#                     f"username={username}",
#                     f"password={password}",
#                     f"notes={notes}"
#                 ])   
#             continue