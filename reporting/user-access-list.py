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


def writeReport(users):
    # username, userEmail, UserUUID, userState, userType, userCreated_at, userUpdated_at,
    # [directly assigned vaults], [groups they belong to]
    with open(f"{outputPath}/user_access_list.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = [
            "userName",
            "userEmail",
            "userUUID",
            "userState",
            "userType",
            "userCreatedAt",
            "userUpdatedAt",
            "directlyAssignedVaults",
            "groups",
        ]
        csvWriter.writerow(fields)

        for user in users:
            csvWriter.writerow(
                [
                    user.name,
                    user.email,
                    user.uuid,
                    user.state,
                    user.type,
                    user.createdAt,
                    user.updatedAt,
                    user.groups,
                    user.vaults,
                ]
            )


def main():
    rawUsers = getAllUsers()
    accountUsers = []

    for user in rawUsers:
        userData = getUserInfo(user["id"])
        userGroups = getUserGroups(user["id"])
        userVaults = getUserVaults(user["id"])
        groups = [(group["name"], group["id"]) for group in userGroups]
        vaults = [(vault["name"], vault["id"]) for vault in userVaults]
        print(groups)
        accountUsers.append(
            User(
                name=user["name"],
                email=user["email"],
                uuid=user["id"],
                state=user["state"],
                type=user["type"],
                createdAt=userData["created_at"],
                updatedAt=userData["updated_at"],
                groups=str(groups).replace("[", "").replace("]", ""),
                vaults=str(vaults).replace("[", "").replace("]", ""),
            )
        )

    writeReport(accountUsers)


main()
