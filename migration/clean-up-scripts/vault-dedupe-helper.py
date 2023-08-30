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

# get a list of vaults the logged-in user has access to
def getVaults():
    return subprocess.run(
        ["op", "vault", "list", "--group=Owners", "--format=json"], check=True, capture_output=True).stdout

# get a list of users and their permissions for a vault
def getVaultUserList(vaultID):
    return subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout

# Get the details of a vault
def getVaultDetails(vaultID):
    return subprocess.run([f"op vault get {vaultID} --format=json"], shell=True, check=True, capture_output=True).stdout

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