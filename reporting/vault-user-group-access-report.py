# A script that provides a list of users who have access to each vault in 
# a 1Password account, and whether that assignment is a direct assignment or
# granted by group membership
#
# This script must be run by a member of the Owners group of a 1Password Business account
import os
import subprocess
import csv
import json
import argparse
import sys

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath 

class User:
    def __init__(self, name, email, uuid, groups):
        self.name = name
        self.email = email
        self.uuid = uuid
        self.groups = []
        self.vaults = []

    def addGroup(self, group):
        self.groups.append(group)

    def addVault(self, vault):
        self.vault.append(vault)

class Vault:
    def __init__(self, name, uuid, users, groups):
        self.name = name
        self.uuid = uuid
        self.users = []
        self.groups = []

    def addUser(self, user):
        self.users.append(user)

class Group:
    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid

vaults = [Vault]
users = [User]
grous = [Group]

def getAllOwnerVaults():
    vaultList = subprocess.run(
        ["op", "vault", "list", "--group=Owners", "--format=json"], check=True, capture_output=True).stdout
    return vaultList


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
    groupMembers = subprocess.run(
        ["op", "group", "user", "list", groupID, "--format=json"], check=True, capture_output=True).stdout
    return groupMembers

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
    pass



# "vaultName", "vaultUUID", "name", "email", "userUUID", "assignment"
# where "assignment" indicates whether a person has access to the vault by direct assignemnt (value would be "direct") or by membership in an assigned group (value would be "group (group name)")
#
#
#
#