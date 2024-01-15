# username, userEmail, UserUUID, userState, userType, userCreated_at, userUpdated_at,  [directly assigned vaults], [groups they belong to]


import os
import subprocess
import csv
import json
import sys
from dataclasses import dataclass

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath


class User:
    def __init__(
        self, name, email, uuid, state, type, createdAt, updatedAt, groups, vaults
    ):
        self.name = name
        self.email = email
        self.uuid = uuid
        self.state = state
        self.type = type
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.groups = groups
        self.vaults = vaults


def getAllUsers():
    return json.loads(
        subprocess.run(
            ["op", "user", "list", "--format=json"], check=True, capture_output=True
        ).stdout
    )


def getUserInfo(userUUID):
    return json.loads(
        subprocess.run(
            ["op", "user", "get", userUUID, "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    )


def getUserVaults(userUUID):
    return json.loads(
        subprocess.run(
            ["op", "vault", "list", f"--user={userUUID}", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    )


def getUserGroups(userUUID):
    return json.loads(
        subprocess.run(
            ["op", "group", "list", f"--user={userUUID}", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    )


def main():
    rawUsers = getAllUsers()
    accountUsers = []

    for user in rawUsers:
        userData = getUserInfo(user["id"])
        userGroups = getUserGroups(user["id"])
        userVaults = getUserVaults(user["id"])

        accountUsers.append(
            User(
                name=user["name"],
                email=user["email"],
                uuid=user["id"],
                state=user["state"],
                type=user["type"],
                createdAt=userData["created_at"],
                updatedAt=userData["updated_at"],
                groups=userGroups,
                vault=userVaults,
            )
        )

    # make accountUsers into a CSV


main()

# for user in userList:
#     userVaults = op vault list --user user
#     usergroups = op group list --user user
