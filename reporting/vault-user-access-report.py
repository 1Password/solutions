# A script that provides a list of users and their permissions for each vault
import os
import subprocess
import csv
import json
import argparse
import sys

parser = argparse.ArgumentParser("User and Permissions Report Generator",
                                 "Generates a csv-like report of each user and their permissions for each vault passed to this script.")
parser.add_argument("--file", action="store", dest="filepath",
                    help="Specify a path to a file containing a line-deliminted list of vault UUIDs to include in the report.")
args = parser.parse_args()

scriptPath = os.path.dirname(__file__)
inputFilePath = args.filepath
outputPath = scriptPath  # Optionally choose an alternative output path here.


# get a list of vaults the logged-in user has access to
def getAllOwnerVaults():
    vaultList = subprocess.run(
        ["op", "vault", "list", "--group=Owners", "--format=json"], check=True, capture_output=True).stdout
    return vaultList


def getSpecifiedVaults():
    with open(inputFilePath, "r", encoding="utf-8") as f:
        vaultList = []
        for id in f:
            vaultList.append(json.loads(subprocess.run(["op", "vault", "get", id.rstrip(
            ), "--format=json"], check=True, capture_output=True).stdout))
    return vaultList

# get a list of users and their permissions for a vault


def getVaultUserList(vaultID):
    vaultUserList = subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
    return vaultUserList

# get all groups in the account


def getVaultGroupList(vaultID):
    vaultGroupList = subprocess.run(
        ["op", "vault", "group", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
    return vaultGroupList


# Given a list of vaults, for each vault, list the users that have access along with their permissions.
# Write the results to a csv file with columns: "vaultName", "vaultUUID", "name","email", "userUUID", "permissions"
def main():
    if inputFilePath is None:
        try:
            vaultList = json.loads(getAllOwnerVaults())
        except (Exception) as e:
            sys.exit("Unable to get a list of vaults for the Owner group. Please sign into 1Password as a member of the Owners group or provide a list of vault UUIDs using the --file option.")
    else:
        vaultList = getSpecifiedVaults()

    with open(f"{outputPath}/output.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = ["vaultName", "vaultUUID", "userName", "groupName",
                  "email", "userOrGroupUUID", "permissions"]
        csvWriter.writerow(fields)
        for vault in vaultList:
            vaultUserList = json.loads(getVaultUserList(vault["id"]))
            vaultGroupList = json.loads(getVaultGroupList(vault["id"]))
            for user in vaultUserList:
                csvWriter.writerow([vault["name"],
                                    vault["id"],
                                    user["name"],
                                    None,
                                    user["email"],
                                    user["id"],
                                    user["permissions"]])
                print(vault["name"], vault["id"], user["name"],
                      user["email"], user["id"], user["permissions"])
            for group in vaultGroupList:
                csvWriter.writerow([vault["name"],
                                    vault["id"],
                                    None,
                                    group["name"],
                                    None,
                                    group["id"],
                                    group["permissions"]])
                print(vault["name"], vault["id"], group["name"],
                      group["id"], group["permissions"])


main()
