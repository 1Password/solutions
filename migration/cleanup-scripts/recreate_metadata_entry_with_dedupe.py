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
    def __init__(self, csvRow):
        self.name = csvRow[0]
        self.uuid = csvRow[1]


def findMetadataVaultUuid(vaults: dict):
    for k, v in vaults.items():
        if v == "❗️ LastPass Imported Shared Folders Metadata":
            return k
    return None


def getVaultItems(vaultID):
    try:
        return subprocess.run(
            f"op item list --vault {vaultID} --format=json",
            shell=True,
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(f"Encountered an error getting items for vault {vaultID}: ", err)
        return


def getItemDetails(vaultUuid, itemUuid):
    try:
        return subprocess.run(
            f"op item get {itemUuid} --vault {vaultUuid} --format=json",
            shell=True,
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(
            f"Encountered an error getting item details for item {itemUuid} vault {vaultUuid}: ",
            err,
        )
        return


def createItem(vaultUuid, itemJson: str):
    from subprocess import Popen, PIPE, STDOUT

    try:
        p = Popen(
            ["op", "item", "create", "--vault", vaultUuid],
            stdout=PIPE,
            stdin=PIPE,
            stderr=PIPE,
        )
        return p.communicate(input=itemJson.encode("utf-8"))[0]
    except Exception as err:
        print(f"Encountered an error creating an item in vault {vaultUuid}: ", err)
        return


def readDate(date):
    return datetime.strptime(date, "%Y-%m-%d %H:%M:%S").timestamp()


def currDate():
    return datetime.strptime(datetime.now, "%Y-%m-%d %H:%M:%S").timestamp


def findOriginalVault(vaults):
    minimum = (0, currDate())
    for i, vault in enumerate(vaults):
        vaultDetails = getVaultDetails(vault.uuid)
        date = readDate(vaultDetails["created_at"])
        if date < minimum[1]:
            minimum = (i, date)
    return vaults[minimum[0]]


# Get the details of a vault
def getVaultDetails(vaultID):
    try:
        return subprocess.run(
            f"op vault get {vaultID} --format=json",
            shell=True,
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(f"Encountered an error getting details for vault {vaultID}: ", err)
        return


def removeImportedPrefix(text):
    prefix = "Imported "
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


def main():
    # all vaults ordered by UUID
    vaults = {}
    # vaults ordered by name
    duplicateVaults = defaultdict(list)
    with open(f"{outputPath}/vaultreport.csv", "r", newline="") as vaultFile:
        csvReader = csv.reader(vaultFile)
        for row in csvReader:
            # we remove the 'Imported ' prefix from all vaults before processing them in case any
            # of them got renamed
            row[0] = removeImportedPrefix(row[0])
            duplicateVaults[row[0]].append(Vault(row))
            vaults[row[1]] = row[0]

    # find the metadata vault
    metadataVaultUuid = findMetadataVaultUuid(vaults)
    # get its items
    metadataItems = json.loads(getVaultItems(metadataVaultUuid))
    itemDetails = [
        json.loads(getItemDetails(metadataVaultUuid, item["id"]))
        for item in metadataItems
    ]
    updatedFields = []
    for item in itemDetails:
        # find the LastPass metadata fields and process them
        for field in item.get("fields", []):
            ids = field["id"].split(".LPID.")
            if len(ids) != 2:
                continue
            vaultUuid = ids[0]
            lpId = ids[1]
            name = vaults.get(vaultUuid, "")
            # We found a metadata entry that points to a vault that exists.
            # We will find the vault with the same name, but that got created first
            # and we will save the new metadata entry
            if len(name) > 0:
                dupVaults = duplicateVaults[name]
                origVault = findOriginalVault(dupVaults)
                updatedFields.append(
                    {
                        "id": f"{origVault.uuid}.LPID.{lpId}",
                        "type": field["type"],
                        "value": field["value"],
                    }
                )

    # create a new metadata record with the updated entries
    newItemFields = [
        {
            "id": "notesPlain",
            "type": "STRING",
            "purpose": "NOTES",
            "label": "notesPlain",
            "value": "",
        }
    ]
    newItemFields.extend(updatedFields)
    newItem = {
        "title": "LastPass Metadata Recreated",
        "category": "SECURE_NOTE",
        "fields": newItemFields,
    }
    createItem(metadataVaultUuid, json.dumps(newItem))


if __name__ == "__main__":
    main()
