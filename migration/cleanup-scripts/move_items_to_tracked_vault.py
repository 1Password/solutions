#!/usr/bin/python3

import os
import subprocess
import csv
import json
from collections import defaultdict
from datetime import datetime

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath  # Optionally choose an alternative output path here.


# Get a list of vaults the logged-in user has access to
def getVaults():
    try:
        return subprocess.run(
            ["op", "vault", "list", "--group=Owners", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
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


main()
