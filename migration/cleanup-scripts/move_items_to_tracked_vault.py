#!/usr/bin/python3

import os
import subprocess
import csv
import json
from collections import defaultdict
from datetime import datetime

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath  # Optionally choose an alternative output path here.


class Vault:
    def __init__(self, name, uuid, itemCount, created, updated):
        self.name = name
        self.uuid = uuid
        self.itemCount = itemCount
        self.created = created
        self.updated = updated


# Get a list of vaults the logged-in user has access to
# Skips any Private vaults and the Metadata vault.
# Fetches all vault details and returns them as a Python object
def getVaults():
    vaults = []
    try:
        getVaultsCommand = subprocess.run(
            ["op", "vault", "list", "--group=Owners", "--format=json"],
            check=True,
            capture_output=True,
        )
        for vault in json.loads(getVaultsCommand.stdout):
            if "Private" in vault["name"]:
                print("Skipping Private vault")
                continue
            if "Imported Shared Folders Metadata" in vault["name"]:
                print("Skipping LastPass Import Metadata vault")
                continue
            processResults = subprocess.run(
                ["op", "vault", "get", vault["id"], "--format=json"],
                check=True,
                capture_output=True,
            )
            if processResults.stderr:
                print(
                    f"encountered an error geting details of a vault: {str(processResults.stderr)}"
                )
                continue
            vaults.append(json.loads(processResults.stdout))
        return vaults
    except Exception as err:
        print(
            f"Encountered an error getting the list of vaults you have access to: ", err
        )
        return


# From a list of vaults within a group of identically-named vaults
def identifyTrackedVault(vaultGroupName, vaults):
    print("Vault group name being processed: ", vaultGroupName)

    # Sort by item count to facilitate identifying tracked and data vaults
    vaults.sort(key=lambda vault: vault.itemCount)

    # Identity vault with greatest number of items, assumption being it has canonical data
    dataVault = vaults[0]

    # Identify vault with zero items, assumption is that is tracked by metadata vault
    trackedVault = vaults[-1]

    # triplicates or greater that are not data or tracked
    otherVaults = vaults[1:-1]

    return dataVault, trackedVault, otherVaults


def getVaultItems(vaultID):
    try:
        return subprocess.run(
            ["op", "item", "list", f"--vault={vaultID}", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(f"Encountered an error getting items for vault {vaultID}: ", err)
        return


# Move items from data vault to tracked vault.
def moveItemsToTrackedVault(trackedVault, dataVault):
    items = json.loads(getVaultItems(dataVault.uuid))
    for item in items:
        try:
            moveCmd = subprocess.run(
                [
                    "op",
                    "item",
                    "move",
                    item["id"],
                    f"--current-vault={dataVault.uuid}",
                    f"--destination-vault={trackedVault.uuid}",
                ],
                check=True,
                capture_output=True,
            )
            if moveCmd.stderr:
                print(moveCmd.err)
        except Exception as err:
            print(
                f"Unable to move item with name '{item['title']}' and ID of '{item['id']}' with error: {err}"
            )


# Rename all untracked vaults
def renameUntrackedVaults(untrackedVaults):
    suffix = 1
    for vault in untrackedVaults:
        newName = f"dup-{vault.name}-{suffix}"
        renameCmd = subprocess.run(
            ["op", "vault", "edit", vault.uuid, f"--name={newName}"],
            check=True,
            capture_output=True,
        )
        print(renameCmd.stdout)
        suffix += 1


# revoke all access and permissions from untracked vaults
def revokeUntrackedVaultPermissions(untrackedVaults):
    for vault in untrackedVaults:
        print(f"Modifying permissions for vault '{vault.name}'.")
        allgroups = json.loads(
            subprocess.run(
                ["op", "vault", "group", "list", vault.uuid, "--format=json"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        allUsers = json.loads(
            subprocess.run(
                ["op", "vault", "user", "list", vault.uuid, "--format=json"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )

        for group in allgroups:
            print(
                f"\t Revoking group {group['name']} permissions for vault '{vault.name}'"
            )
            groupRevokeCmd = subprocess.run(
                [
                    "op",
                    "vault",
                    "group",
                    "revoke",
                    f"--vault={vault.uuid}",
                    f"--group={group['id']}",
                    "--no-input",
                ],
                capture_output=True,
            )
            if groupRevokeCmd.stderr:
                print(f"complete! str({groupRevokeCmd.stderr})")

        for user in allUsers:
            print(
                f"\t Revoking user {str(user['name'])} permissions for vault '{vault.name}'"
            )
            userRevokeCmd = subprocess.run(
                [
                    "op",
                    "vault",
                    "user",
                    "revoke",
                    f"--vault={vault.uuid}",
                    f"--user={user['id']}",
                    "--no-input",
                ],
                capture_output=True,
            )
            if userRevokeCmd.stderr:
                print(f"ERROR! {str(userRevokeCmd.stderr)}")


def main():
    vaults = []
    vaultGroups = {}
    vaultDetails = getVaults()

    for vault in vaultDetails:
        vaults.append(
            Vault(
                name=vault["name"],
                uuid=vault["id"],
                created=vault["created_at"],
                updated=vault["updated_at"],
                itemCount=vault["items"],
            )
        )

    # Ensure vaults are alpha sorted
    vaults.sort(key=lambda vault: vault.name)

    # Create a dict containing groups of identically named vaults.
    # Dict keys are a vault name representing all vaults with that name.
    # The value for each key is a list of Vault class instances
    for vault in vaults:
        if vault.name not in vaultGroups:
            vaultGroups[vault.name] = []
        vaultGroups[vault.name].append(vault)

    for vaultGroupName, vaults in vaultGroups.items():
        if len(vaults) == 1:
            print(
                f"Vault with name {vaultGroupName} is unique. Skipping de-duplication."
            )
            continue
        trackedVault, dataVault, otherVaults = identifyTrackedVault(
            vaultGroupName, vaults
        )

        print(
            "\tTracked Vault: ",
            trackedVault.name,
            "ITEMS: ",
            trackedVault.itemCount,
            "\n\tData Vault: ",
            dataVault.name,
            "ITEMS: ",
            dataVault.itemCount,
            "\n\tOther vaults: ",
            str(otherVaults),
        )
        moveItemsToTrackedVault(trackedVault, dataVault)
        untrackedVaults = otherVaults
        untrackedVaults.append(dataVault)
        renameUntrackedVaults(untrackedVaults)
        revokeUntrackedVaultPermissions(untrackedVaults)


main()
