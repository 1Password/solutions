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


users = []
groups = []


class User:
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


class Group:
    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid
        self.users = []

    def addUser(self, user: User):
        self.users.append(user)


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
        users.append(User(email=user['email'],
                     name=user['name'], uuid=user['id']))


def getAllGroups():
    accountGroupList = subprocess.run(
        ["op", "group", "list", "--format=json"], check=True, capture_output=True).stdout
    for group in json.loads(accountGroupList):
        # groups.update(
        #     {group['id']: Group(name=group['name'], uuid=group['id'])})
        groups.append(Group(name=group['name'], uuid=group['id']))


# def getVaultUserList(vaultID):
#     vaultUserList = subprocess.run(
#         ["op", "vault", "user", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
#     return vaultUserList

# def getVaultGroupList(vaultID):
#     vaultGroupList = subprocess.run(
#         ["op", "vault", "group", "list", vaultID, "--format=json"], check=True, capture_output=True).stdout
#     return vaultGroupList

# def getGroupMembers(groupID):
#     # Array of group members
#     groupMembers = subprocess.run(
#         ["op", "group", "user", "list", groupID, "--format=json"], check=True, capture_output=True).stdout
#     return groupMembers

def writeReport():
    with open(f"{outputPath}/vaultAccessReport.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = ["vaultName", "vaultUUID", "name",
                  "email", "userUUID", "assignment"]
        csvWriter.writerow(fields)
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
    getAllUsers()
    getAllGroups()
    # for vault in Vault.getAll():
    #     print(vault.name, " ", vault.uuid)

    print(Vault.getByID("2pmkai6em5jqxziemutdy3aepy").name)
    # for vault in iter(vaults):
    #     print('VAULTS: ', vault.name)
    # for user in users:
    #     print('\tUSER: ', user.name)
    # for group in groups:
    #     print('GROUP: ', group.name)


main()

# "vaultName", "vaultUUID", "name", "email", "userUUID", "assignment"
# where "assignment" indicates whether a person has access to the vault by direct assignemnt (value would be "direct") or by membership in an assigned group (value would be "group (group name)")
#
#
#
#
