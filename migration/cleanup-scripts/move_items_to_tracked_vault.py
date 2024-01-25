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
def getVaults():
    try:
        getVaultsCommand = subprocess.run(
            ["op", "vault", "list", "--group=Owners", "--format=json"],
            check=True,
            capture_output=True,
        )
        return getVaultsCommand.stdout
    except Exception as err:
        print(
            f"Encountered an error getting the list of vaults you have access to: ", err
        )
        return


# Get the details of a vault
def getVaultDetails(vaultID):
    try:
        return subprocess.run(
            ["op", "vault", "get", f"{vaultID}", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(f"Encountered an error getting details for vault {vaultID}: ", err)
        return


def main():
    vaults = json.loads(getVaults())

    # Collect all vaults
    # Identify identically named vaults
    # For a set of duplicates, sort by number of items
    # Move items from vault with most items to vault with zero
    # prefix duplicates with `dup-` and if more than one, add numeric suffix
    # remove all permissions from non-canonical vaults


main()
