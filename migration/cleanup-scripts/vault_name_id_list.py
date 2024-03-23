###
# A script that will produce a csv-like report to assist with de-duplication.
# Outputs vaultName, vaultUUID, itemCount, vault creation date, vault updated, number of users
###
import os
import subprocess
import csv
import json
from datetime import datetime

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath  # Optionally choose an alternative output path here.


# Get a list of vaults the logged-in user has access to
def getVaults():
    try:
        return subprocess.run(
            "op vault list --group=Owners --format=json",
            shell=True,
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(
            f"Encountered an error getting the list of vaults you have access to: ", err
        )
        return


def main():
    vaultList = json.loads(getVaults())
    with open(f"{outputPath}/vaultreport.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = [
            "vaultName",
            "vaultUUD",
        ]
        csvWriter.writerow(fields)

        for vault in vaultList:
            if vault["name"] == "Private":
                continue

            csvWriter.writerow(
                [
                    vault["name"],
                    vault["id"],
                ]
            )

            print(
                vault["name"],
                vault["id"],
            )


main()
