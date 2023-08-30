###
# A script that will produce a csv-like report to assist with de-duplication. 
# Outputs vaultName, vaultUUID, itemCount, vault creation date, vault updated, number of users
###
import os
import subprocess
import csv
import json
from datetime import datetime

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath  # Optionally choose an alternative output path here.

# Get a list of vaults the logged-in user has access to
def getVaults():
    return subprocess.run(
        "op vault list --group=Owners --format=json", shell=True, check=True, capture_output=True).stdout

# Get a list of users and their permissions for a vault
def getVaultUserList(vaultID):
    return subprocess.run(f"op vault user list {vaultID} --format=json", shell=True, check=True, capture_output=True).stdout

# Get the details of a vault
def getVaultDetails(vaultID):
    return subprocess.run(f"op vault get {vaultID} --format=json", shell=True, check=True, capture_output=True).stdout

# Make dates returned from the CLI a bit nicer
def formatDate(date):
    isoDate = datetime.fromisoformat(date)
    return f"{isoDate.year}-{isoDate.month}-{isoDate.day} {isoDate.hour}:{isoDate.minute}:{isoDate.second}"

def main():
    vaultList = json.loads(getVaults())
    with open(f"{outputPath}/vaultreport.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = ["vaultName", "vaultUUD", "itemCount", "vaultCreated", "vaultUpdated", "userCount"]
        csvWriter.writerow(fields)
        
        for vault in vaultList:
            if vault["name"] == "Private":
                continue
            vaultUserList = json.loads(getVaultUserList(vault["id"]))
            vaultDetails = json.loads(getVaultDetails(vault["id"]))
            userCount = len(vaultUserList)
            dateCreated = formatDate(vaultDetails["created_at"])
            dateUpdated = formatDate(vaultDetails["updated_at"])

            csvWriter.writerow([
                vault["name"],
                vault["id"],
                vaultDetails["items"],
                dateCreated,
                dateUpdated,
                userCount
            ]) 
main()