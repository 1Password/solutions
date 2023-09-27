# A script that provides a list of users who have access to each vault in
# a 1Password account, and whether that assignment is a direct assignment or
# granted by group membership
#
# This script must be run by a member of the Owners group of a 1Password Business account
import os
import subprocess
import csv
import json
from dataclasses import dataclass
import argparse
import sys

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath


class User:
    users = []

    def __init__(self, name, email, uuid, groups=None):
        self.name = name
        self.email = email
        self.uuid = uuid
        self.groups = []
        self.vaults = []

    def addGroup(self, group):
        self.groups.append(group)

    def addVault(self, vault):
        self.vault.append(vault)

    @classmethod
    def getAll(cls):
        return [inst for inst in cls.users]

    @classmethod
    def getByID(cls, userID):
        for user in cls.users:
            if user.uuid == userID:
                return user


class Group:
    groups = []

    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid
        self.users = []

    def addUser(self, user: User):
        self.users.append(user)

    @classmethod
    def getAll(cls):
        return [inst for inst in cls.groups]

    @classmethod
    def getByID(cls, groupID):
        for group in cls.groups:
            if group.uuid == groupID:
                return group


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
        ["op", "vault", "list", "--group=Owners", "--format=json"], check=True, capture_output=True).stdout
    for vault in json.loads(vaultList):
        Vault(name=vault['name'], uuid=vault['id'],)
        # vaults.update({vault["id"]: Vault(vault['name'], vault['id'])})
        # vaults.append(Vault(vault['name'], vault['id']))


def getAllUsers():
    accountUserList = subprocess.run(
        ["op", "user", "list", "--format=json"], check=True, capture_output=True).stdout
    for user in json.loads(accountUserList):
        # users.update({user['id']: User(email=user['email'],
        #              name=user['name'], uuid=user['id'])})
        User(email=user['email'], name=user['name'], uuid=user['id'])


def getAllGroups():
    accountGroupList = subprocess.run(
        ["op", "group", "list", "--format=json"], check=True, capture_output=True).stdout
    for group in json.loads(accountGroupList):
        # groups.update(
        #     {group['id']: Group(name=group['name'], uuid=group['id'])})
        Group(name=group['name'], uuid=group['id'])


def getVaultUserList(vaultID):
    vaultUserList = subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
    return vaultUserList


def getVaultGroupList(vaultID):
    vaultGroupList = subprocess.run(
        ["op", "vault", "group", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
    return vaultGroupList


def getGroupMembers(groupID):
    # Array of group members
    try:
        groupMembers = subprocess.run(
            ["op", "group", "user", "list", groupID, "--format=json"], check=True, capture_output=True).stdout
    except (Exception):
        groupMembers = []
        print("group has no members")

    return groupMembers


def writeReport(vaults: Vault):
    for vault in vaults:
        vaultName = vault.name
        vaultUUID = vault.uuid
        users = vault.users
        groups = vault.groups
        print(f"VAULT: {vaultName} \t {vaultUUID}")
        for user in users:
            print(
                f"USERS: {user['name']} \t {user['uuid']} \t {user['assignment']}")
        for group in groups:
            print(f"GROUPS: {group['name']} \n\n")

    # with open(f"{outputPath}/vaultAccessReport.csv", "w", newline="") as outputFile:
    #     csvWriter = csv.writer(outputFile)
    #     fields = ["vaultName", "vaultUUID", "name",
    #               "email", "userUUID", "assignment"]
    #     csvWriter.writerow(fields)
        # for vault in vaults:
        #     vaultUserList = json.loads(getVaultUserList(vault["id"]))
        #     for user in vaultUserList:
        #         csvWriter.writerow([vault["name"],
        #                             vault["id"],
        #                             user["name"],
        #                             user["email"],
        #                             user["id"],
        #                             user["permissions"]])
        #         print(vault["name"], vault["id"], user["name"], user["email"], user["id"], user["permissions"])


def main():
    # Populate initial data
    getAllOwnerVaults()

    # Get user assignments and group assignments
    vaults = Vault.getAll()
    for vault in vaults[:5]:
        print(f"\tPROCESSING {vault.name}. This may take a moment...")
        users = json.loads(getVaultUserList(vault.uuid))
        for user in users:
            vault.users.append(
                {'name': user['name'], 'email': user['email'], 'uuid': user['id'], 'assignment': 'Direct'})

    # For assigned groups, decompose into individual users
        groups = json.loads(getVaultGroupList(vault.uuid))
        for group in groups:
            vault.groups.append(
                {'name': group['name'], 'groupUUID': group['id']})
            groupUsers = json.loads(getGroupMembers(group['id']))
            if groupUsers is not None:
                for groupUser in groupUsers:
                    vault.users.append(
                        {'name': groupUser['name'], 'email': groupUser['email'], 'uuid': groupUser['id'], 'assignment': f'group ({group["name"]})'})

    writeReport(vaults)


main()

# "vaultName", "vaultUUID", "name", "email", "userUUID", "assignment"
# where "assignment" indicates whether a person has access to the vault
# by direct assignemnt (value would be "direct") or by membership in an
# assigned group (value would be "group (group name)")
#
#
#
#
