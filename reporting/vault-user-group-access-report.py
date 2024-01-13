# A script that provides a list of users who have access to each vault in
# a 1Password account, and whether that assignment is a direct assignment or
# granted by group membership, and their vault permissions
#
# This script must be run by a member of the Owners group of a 1Password Business account
import os
import subprocess
import csv
import json
import sys
from dataclasses import dataclass

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath


class User:
    users = []

    def __init__(self, name, email, uuid, state, groups=None):
        self.name = name
        self.email = email
        self.uuid = uuid
        self.state = state
        self.groups = []
        self.vaults = []


class Group:
    groups = []

    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid
        self.users = []


class Vault:
    vaults = []

    def __init__(self, name, uuid, users=None, groups=None):
        self.name = name
        self.uuid = uuid
        self.users = []
        self.groups = []
        Vault.vaults.append(self)

    def addUser(self, user):
        self.users.append(user)

    @classmethod
    def getAll(cls):
        return [inst for inst in cls.vaults]

    @classmethod
    def getByID(cls, vaultID):
        for vault in cls.vaults:
            if vault.uuid == vaultID:
                return vault


def getAllOwnerVaults():
    vaultList = subprocess.run(
        ["op", "vault", "list", "--group=Owners", "--format=json"],
        check=True,
        capture_output=True,
    ).stdout
    for vault in json.loads(vaultList):
        Vault(
            name=vault["name"],
            uuid=vault["id"],
        )


def getAllUsers():
    accountUserList = subprocess.run(
        ["op", "user", "list", "--format=json"], check=True, capture_output=True
    ).stdout
    for user in json.loads(accountUserList):
        User(
            email=user["email"], name=user["name"], uuid=user["id"], state=user["state"]
        )


def getAllGroups():
    accountGroupList = subprocess.run(
        ["op", "group", "list", "--format=json"], check=True, capture_output=True
    ).stdout
    for group in json.loads(accountGroupList):
        Group(name=group["name"], uuid=group["id"])


def getVaultUserList(vaultID):
    vaultUserList = subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"],
        check=True,
        capture_output=True,
    ).stdout
    return vaultUserList


def getVaultGroupList(vaultID):
    vaultGroupList = subprocess.run(
        ["op", "vault", "group", "list", vaultID, "--format=json"],
        check=True,
        capture_output=True,
    ).stdout
    return vaultGroupList


def getGroupMembers(groupID):
    try:
        groupMembers = subprocess.run(
            ["op", "group", "user", "list", groupID, "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    # If the vault has no assigned groups, prevent the script from stopping when None is returned
    except Exception:
        groupMembers = []
        print("group has no members")

    return groupMembers


def writeReport(vaults: Vault):
    with open(f"{outputPath}/vaultAccessReport.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = [
            "vaultName",
            "vaultUUID",
            "name",
            "email",
            "userUUID",
            "status",
            "assignment",
            "permissions",
        ]
        csvWriter.writerow(fields)
        for vault in vaults:
            vaultName = vault.name
            vaultUUID = vault.uuid
            # write each row
            for user in vault.users:
                csvWriter.writerow(
                    [
                        vaultName,
                        vaultUUID,
                        user["name"],
                        user["email"],
                        user["uuid"],
                        user["state"],
                        user["assignment"],
                        user["permissions"],
                    ]
                )


def main():
    counter = 1
    # Populate initial data
    try:
        getAllOwnerVaults()
    except Exception as e:
        sys.exit(
            "Unable to get a list of vaults for the Owner group. Please sign into 1Password as a member of the Owners group. Error: ",
            e,
        )

    # Get user assignments and group assignments
    vaults = Vault.getAll()
    vaultCount = len(vaults)
    for vault in vaults:
        print(
            f'\tPROCESSING vault {counter}/{vaultCount} "{vault.name}". This may take a moment...'
        )
        try:
            users = json.loads(getVaultUserList(vault.uuid))
        except Exception as e:
            sys.exit(
                f"Unable to get a list of users directly assigned to vault {vault.name}. Error: {e}"
            )
        for user in users:
            vault.users.append(
                {
                    "name": user["name"],
                    "email": user["email"],
                    "uuid": user["id"],
                    "assignment": "Direct",
                    "state": user["state"],
                    "permissions": user["permissions"],
                }
            )

        # For assigned groups, decompose into individual users
        try:
            groups = json.loads(getVaultGroupList(vault.uuid))
        except Exception as e:
            sys.exit(
                f"Unable to get a list of groups assigned to vault {vault.name}. Error: {e}"
            )
        for group in groups:
            vault.groups.append(
                {
                    "name": group["name"],
                    "groupUUID": group["id"],
                    "permissions": group["permissions"],
                }
            )
            try:
                groupUsers = json.loads(getGroupMembers(group["id"]))
            except Exception as e:
                sys.exit(
                    f"Unable to get a list of group members in group {group['name']} assigned to vault {vault.name}. Error: {e}"
                )
            if groupUsers is not None:
                for groupUser in groupUsers:
                    vault.users.append(
                        {
                            "name": groupUser["name"],
                            "email": groupUser["email"],
                            "uuid": groupUser["id"],
                            "assignment": f'Group ({group["name"]})',
                            "state": groupUser["state"],
                            "permissions": group["permissions"],
                        }
                    )
        counter += 1
    try:
        writeReport(vaults)
    except Exception as e:
        sys.exit("Unable to write data to a file on disk.")


main()
