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


# Check CLI version and use the appropriate `op vault list` command for that version.
def checkCLIVersion():
    global opVersion
    r = subprocess.run(["op", "--version", "--format=json"], capture_output=True)
    major, minor = r.stdout.decode("utf-8").rstrip().split(".", 2)[:2]
    if minor >= "25":
        opVersion = "2.25"
    else:
        opVersion = "2.21"


# get a list of vaults the logged-in user has access to
def getAllOwnerVaults():
    global opVersion
    command = ""
    if opVersion == "2.25":
        command = ["op", "vault", "list", "--permission=manage_vault", "--format=json"]
    if opVersion == "2.21":
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


def main():
    checkCLIVersion()

    vaultList = json.loads(getAllOwnerVaults())
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
            if "Private" in vault["name"]:
                print(f"Skipping vault \"{vault['name']}\" because it is Private.")
                continue
            print(f"\t⌛ Processing vault \"{vault['name']}\"")
            groups = json.loads(getVaultGroupList(vault))

            groupCount = len(groups)
            users = json.loads(getVaultUserList(vault))
            userCount = len(users)

            # Generate comma-seperated string of group names
            groupNamesRaw = [group["name"] for group in groups]
            groupNames = ", ".join(groupNamesRaw)
            # This is only being called to get item count. If item count isn't critical, omitting it could save a lot of time.
            vaultDetails = json.loads(getVaultDetails(vault))
            itemCount = vaultDetails["items"]
            csvWriter.writerow(
                [
                    vault["name"],
                    vault["id"],
                    groupCount,
                    userCount,
                    groupNames,
                    itemCount,
                ]
            )


main()
