###
# A script that will produce a csv-like report to assist with de-duplication. 
# Outputs vaultName, vaultUUID, itemCount, vault creation date, vault updated, number of users
###
import os
import subprocess
import csv
import json

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath  # Optionally choose an alternative output path here.

# get the UUID of the user running the CLI script for use elsewhere in the script.  
def getMyUUID():
    subprocess.run(["op signin"], shell=True, check=True)
    return json.loads(subprocess.run(["op whoami --format=json"], check=True, shell=True, capture_output=True).stdout)['user_uuid']

myUUID = getMyUUID()


# get a list of vaults the logged-in user has access to
def getVaults():
    vaultList = subprocess.run(
        ["op", "vault", "list", "--group=Owners", "--format=json"], check=True, capture_output=True).stdout
    return vaultList

# get a list of users and their permissions for a vault
def getVaultUserList(vaultID):
    vaultUserList = subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
    return vaultUserList

def getVaultDetails(vaultID):
    return subprocess.run([f"op vault get {vaultID} --format=json"], shell=True, check=True, capture_output=True).stdout
# def getVaultItems(vaultID):
#     vaultItemList = subprocess.run(f"op item list --vault={vaultID} --format=json", shell=True, check=True, capture_output=True).stdout
#     return vaultItemList

# May not be necessary for this script 
# def changeMyPermissions(vaultUserData, vaultUUID, action):
#     myData = next((user for user in vaultUserData if user["id"] == myUUID), None)
#     print(myData)
#     if myData is not None: # TODO: this is broken because `op vault list` will not list vaults I only have `manage vault` permission on.
#         permissions = myData["permissions"]
#         if "view_items" not in permissions:
#             subprocess.run([f"op vault user {action} --vault={vaultUUID} --permissions=view_items"])
#             print(f"permissions for {vaultUUID} updated")
#         print(permissions)


def main():
    vaultList = json.loads(getVaults())
    with open(f"{outputPath}/vault-item-report.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = ["vaultName", "vaultUUD", "itemCount", "vaultCreated", "vaultUpdated", "userCount"]
        csvWriter.writerow(fields)
        
        for vault in vaultList:
            if vault["name"] == "Private":
                continue
            vaultUserList = json.loads(getVaultUserList(vault["id"]))
            vaultDetails = json.loads(getVaultDetails(vault["id"]))
            
            userCount = len(vaultUserList)

            csvWriter.writerow([
                vault["name"],
                vault["id"],
                vaultDetails["items"],
                vaultDetails["created_at"],
                vaultDetails["updated_at"],
                userCount
            ]) 
main()