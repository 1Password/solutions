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
                print("Skipping private vault")
                continue
            if "Imported Shared Folders Metadata" in vault["name"]:
                print("Skipping metadata vault")
                continue
            processResults = subprocess.run(
                ["op", "vault", "get", vault["id"], "--format=json"],
                check=True,
                capture_output=True,
            )
            if processResults.stderr:
                print(
                    f"encountered an error geting details of a vault: {processResults.stderr}"
                )
                continue
            vaults.append(json.loads(processResults.stdout))
        return vaults
    except Exception as err:
        print(
            f"Encountered an error getting the list of vaults you have access to: ", err
        )
        return


def main():
    vaults = []
    vaultGroups = {}
    vaultDetails = getVaults()
    # vaultDetails = getVaultDetails(vaultList)

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

    for groupName, vaults in vaultGroups.items():
        print(groupName)
        for vault in vaults:
            print(f"\t Name: ", vault.name, "Items: ", vault.itemCount)

    # Collect all vaults
    # Identify identically named vaults
    # For a set of duplicates, sort by number of items
    # Move items from vault with most items to vault with zero
    # prefix duplicates with `dup-` and if more than one, add numeric suffix
    # remove all permissions from non-canonical vaults


main()
