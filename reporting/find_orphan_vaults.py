#!/usr/bin/python3
import os
import subprocess
import csv
import json
import argparse
import sys

parser = argparse.ArgumentParser(
    "Find vaults that are only accessible to the Owners group, or Owners and Administrators group, suggesting they may be unused or orphaned.",
    "Outputs a CSV report.",
)

args = parser.parse_args()

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath  # Optionally choose an alternative output path here.
opVersion = ""


# Check CLI version
def checkCLIVersion():
    r = subprocess.run(["op", "--version", "--format=json"], capture_output=True)
    major, minor = r.stdout.decode("utf-8").rstrip().split(".", 2)[:2]
    if not major == 2 and not int(minor) >= 25:
        opVersion = "2.21"
    else:
        opVersion = "2.25"


# get a list of vaults the logged-in user has access to
def getAllOwnerVaults():
    if opVersion == "2.21":
        command = ["op", "vault", "list", "--permission=manage_vault", "--format=json"]
    if opVersion == "2.25":
        command = ["op", "vault", "list", "--group=Owners", "--format=json"]
    r = subprocess.run(
        command,
        check=True,
        capture_output=True,
    )
    if r.returncode != 0:
        sys.exit(
            f"🔴 Unable to get a list of vaults you have Manage Vault permissions for. Error: ",
            r.stderr.decode("utf-8"),
        )
    return r.stdout


# get a list of users and their permissions for a vault
def getVaultUserList(vault):
    r = subprocess.run(
        ["op", "vault", "user", "list", vault["id"], "--format=json"],
        capture_output=True,
    )
    if r.returncode != 0:
        print(
            f"🔴 Unable to get a list of users for vault {vault['name']} and UUID {vault['id']}. Error: ",
            r.stderr.decode("utf-8"),
        )
        return
    return r.stdout


# get all groups in the account
def getVaultGroupList(vault):
    r = subprocess.run(
        ["op", "vault", "group", "list", vault["id"], "--format=json"],
        capture_output=True,
    )
    if r.returncode != 0:
        print(
            f"🔴 Unable to get a list of groups for vault {vault['name']} and UUID {vault['id']}. Error: ",
            r.stderr.decode("utf-8"),
        )
        return
    return r.stdout


def getVaultDetails(vault):
    r = subprocess.run(
        ["op", "vault", "get", vault["id"], "--format=json"], capture_output=True
    )
    if r.returncode != 0:
        print(
            f"🔴 Unable to get details for vault {vault['name']} and UUID {vault['id']}. Error: ",
            r.stderr.decode("utf-8"),
        )
        return
    return r.stdout


# - Number of users per vault (ex Owners) (op vault user list)
# - Number of groups per vault (ex Owners) (op vault group list)
# - Group/s and names associated with each vault (op vault group list)
# - Number of items in vault (op vault get)
# - Vault name (op vault list)
# - Vault uuid (op vault list)890
# - Exclude the zzArchived vaults (still dealing with these)
# - Bonus feature: Nummber of users in group/s


# Given a list of vaults, for each vault, list the users that have access along with their permissions.
# Write the results to a csv file with columns: "vaultName", "vaultUUID", "name","email", "userUUID", "permissions"
def main():
    checkCLIVersion()

    vaultList = json.loads(getAllOwnerVaults())
    print(vaultList)
    with open(f"{outputPath}/orphan_vault_report.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = [
            "vaultName",
            "vaultUUID",
            "groupCount",
            "userCount",
            "groupList",
            "itemCount",
        ]
        csvWriter.writerow(fields)
        for vault in vaultList:
            # Excluding zzArchived vaults
            if vault["name"].startswith("zzArchive"):
                continue

            groups = json.loads(getVaultGroupList(vault))

            # Subtracting one from length of group array to exclude Owners group, since Owners will always be listed for all vaults.
            groupCount = len(groups) - 1
            users = json.loads(getVaultUserList(vault))
            userCount = len(users)

            # This is only being called to get item count. If item count isn't critical, omitting it could save a lot of timem.
            # TODO: Implement basic backoff to handle rate limiting.
            vaultDetails = json.loads(getVaultDetails(vault))
            itemCount = vaultDetails["items"]


main()
