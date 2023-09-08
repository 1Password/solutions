# A script that provides a list of users and the names of every item contained in a list of vaultUUIDs
import os
import sys
import subprocess
import csv
import json
import argparse

parser = argparse.ArgumentParser("User and Items Report Generator", "Generates a csv-like report listing all item names and UUIDs and all users who have access to each vault passed to this script.")
parser.add_argument("--file", action="store", dest="filepath", help="Specify a path to a file containing a line-deliminted list of vault UUIDs to include in the report.")
args = parser.parse_args()

scriptPath = os.path.dirname(__file__)
inputFilePath = args.filepath
outputPath = scriptPath  # Optionally choose an alternative output path here.


# get the UUID of the user running the CLI script for use elsewhere in the script.  
def getMyUUID():
    subprocess.run(["op signin"], shell=True, check=True)
    return json.loads(subprocess.run(["op whoami --format=json"], check=True, shell=True, capture_output=True).stdout)['user_uuid']

try: 
    myUUID = getMyUUID() 
except (Exception) as e:
    sys.exit("Unable to get your UUID. Please ensure you are signed into 1Password and try again.") 

# get a list of vaults the logged-in user has access to
def getAllOwnerVaults():
    vaultList = subprocess.run(["op", "vault", "list", "--group=Owners", "--format=json"], check=True, capture_output=True).stdout
    return vaultList

def getSpecifiedVaults():
    with open(inputFilePath, "r", encoding="utf-8") as f:
        vaultList = []
        for id in f:
            vaultList.append(json.loads(subprocess.run(["op", "vault", "get", id.rstrip(), "--format=json"], check=True, capture_output=True).stdout))
    return vaultList

# get a list of users and their permissions for a vault
def getVaultUserList(vaultID):
    vaultUserList = subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
    return vaultUserList

def getVaultItems(vaultID):
    vaultItemList = subprocess.run(f"op item list --vault={vaultID} --format=json", shell=True, check=True, capture_output=True).stdout
    return vaultItemList
    

# check the Owner's permissions for a vault. Add View Item permission if not granted
def addViewPermissions(vaultUserData, vaultUUID):
    myData = next((user for user in vaultUserData if user["id"] == myUUID), None)
    if myData is None:
            subprocess.run([f"op vault user grant --user={myUUID} --vault={vaultUUID} --permissions=view_items"], shell=True, check=True, capture_output=True)
            print(f"View permission for {vaultUUID} granted")
            return True
    elif myData is not None:
        permissions = myData["permissions"]
        if "view_items" not in permissions:
            subprocess.run([f"op vault user grant --user={myUUID} --vault={vaultUUID} --permissions=view_items"], shell=True, check=True, capture_output=True)
            print(f"view permission for {vaultUUID} granted")
            return True
    else: return

# remove the View Item permission. 
def removeViewPermissions(vaultUserData, vaultUUID):
    myData = next((user for user in vaultUserData if user["id"] == myUUID), None)
    if myData is None:
            subprocess.run([f"op vault user revoke --user={myUUID} --vault={vaultUUID} --permissions=view_items"], shell=True, check=True, capture_output=True)
            print(f"View permission for vault {vaultUUID} revoked")
    elif myData is not None:
        permissions = myData["permissions"]
        if "view_items" not in permissions:
            subprocess.run([f"op vault user revoke --user={myUUID} --vault={vaultUUID} --permissions=view_items"], shell=True, check=True, capture_output=True)
            print(f"View permission for vault {vaultUUID} revoked")

def main():
    if inputFilePath is None:
        try:
            vaultList = json.loads(getAllOwnerVaults())
        except (Exception) as e:
            sys.exit("Unable to get a list of vaults for the Owner group. Please sign into 1Password as a member of the Owners group or provide a list of vault UUIDs using the --file option.")
    else:
        vaultList = getSpecifiedVaults()
    
    with open(f"{outputPath}/vault-item-report.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = ["vaultName", "vaultUUD", "userName", "userEmail", "userUUID", "userPermissions", "itemName", "itemUUID"]
        csvWriter.writerow(fields)
        
        for vault in vaultList:
            permissionsModified = False
            if "Private Vault" in vault["name"] or vault["name"] == "Private": # skip your own Private vault and Private vaults of pending users 
                continue
            vaultUserList = json.loads(getVaultUserList(vault["id"]))
            permissionsModified = addViewPermissions(vaultUserList, vault["id"])

            try:
                itemList = json.loads(getVaultItems(vault["id"]))
            except (Exception) as e:
                print(f"ERR: Unable to list items in vault {vault['id']}. It's possible the 1Password CLI has been removed from the 'App Access' list for this vault. Error: ", e) 
                continue

            csvWriter.writerow([
                vault["name"],
                vault["id"],
                None,
                None,
                None,
                None,
                None,
                None
            ])
            print(vault["name"], vault["id"])
            
            for user in vaultUserList:
                csvWriter.writerow([
                    None,
                    None,
                    user["name"],
                    user["email"],
                    user["id"],
                    user["permissions"],
                    None,
                    None
                ])
                print(user["name"],user["email"],user["id"],user["permissions"])

            for item in itemList:
                csvWriter.writerow([
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    item["title"],
                    item["id"]
                ])
                print(item["title"],item["id"])
            if permissionsModified == True: # if permission was added, remove the permission
                removeViewPermissions(vaultUserList, vault["id"])
main()