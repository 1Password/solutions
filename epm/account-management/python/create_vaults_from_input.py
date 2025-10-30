#!/usr/bin/python3
import argparse
import csv
import json
import subprocess
import sys
import time

parser = argparse.ArgumentParser(
    "Create a 1Password vault for each name in a list of vault names provided as a plaintext file using the --file flag.",
    "By default, you will have full permissions on each vault created by this script."
    "User the --remove-me flag if you'd like to revoke your own access to the vault after it is created. Members of the Owners and Administrators groups will still be able to manage this vault.",
)
parser.add_argument(
    "--file",
    action="store",
    dest="filepath",
    help="Specify the path to a CSV file containing the required input data.",
    required=True,
)

parser.add_argument(
    "--remove-me",
    action="store_true",
    dest="removeMe",
    help="Remove yourself from the vaults created by this script. To avoid rate limiting, this aggressively throttles the script and each vault will take 11 seconds to process.",
)

args = parser.parse_args()


# Get the User UUID of the person running the script. This is required for other parts of the script.
def getMyUUID() -> str:
    print("Ensuring you're signed into 1Password and obtaining your User ID.\n")
    r = subprocess.run(["op", "whoami", "--format=json"], capture_output=True)

    # Catch error and kill process
    if r.returncode != 0:
        sys.exit(
            f"🔴 Unable to get your user UUID. Make sure you are are signed into the 1Password CLI. Error: {r.stderr.decode('utf-8')}"
        )
    print(f"🟢 Obtained your User ID: {json.loads(r.stdout)['user_uuid']} \n")
    return json.loads(r.stdout)["user_uuid"]


# Grants the group access to the corrosponding vault with defined permissions.
def createVaultWithName(vault: str):
    retries = 0
    maxRetries = 3
    print(f"\t⌛ Attempting to create vault called {vault}.")
    while retries < maxRetries:
        r = subprocess.run(
            [
                "op",
                "vault",
                "create",
                vault,
            ],
            capture_output=True,
        )
        # time.sleep(11)
        # Handle rate limit error
        if "rate-limited" in r.stderr.decode("utf-8"):
            # Retry after waiting for 60 seconds
            print(r.stderr.decode("utf-8"))
            print("💤 Sleeping for 10 minutes, go grab a coffee.")
            time.sleep(600)
            retries += 1
        # Catch error but continue
        elif r.returncode != 0 and "rate-limited" not in r.stderr.decode("utf-8"):
            print(
                f"\t🔴 Unable to create vault named '{vault}'. Error: ",
                r.stderr.decode("utf-8"),
            )
            break
        else:
            print(f"\t🟢 Successfully created '{vault}'")
            break


# Revokes vault access for the person running the script.
def removeCreatorPermissionsFor(vault: str, userID: str):
    retries = 0
    maxRetries = 3
    print(f"\t⌛ Attempting to remove your access to the newly created vault {vault}.")
    while retries < maxRetries:
        r = subprocess.run(
            ["op", "vault", "user", "revoke", f"--user={userID}", f"--vault={vault}"],
            capture_output=True,
        )
        time.sleep(11)
        # Handle rate limit error
        if "rate-limited" in r.stderr.decode("utf-8"):
            # Retry after waiting for 60 seconds
            print(r.stderr.decode("utf-8"))
            print("💤 Sleeping for 10 minutes, go grab a coffee.")
            time.sleep(600)
            retries += 1
        # Catch error but continue
        elif r.returncode != 0 and "rate-limited" not in r.stderr.decode("utf-8"):
            print(
                f"\t🔴 There was an issue removing your access to the vault {vault}. Error: ",
                r.stderr.decode("utf-8"),
            )
            return
        print(f"\t🟢 Succeeded in removing your access to vault {vault}.\n\n")
        return


def main():
    myUUID: str = getMyUUID()
    # Open the csv passed via the --file flag
    with open(args.filepath, "r", newline="", encoding="utf-8") as inputFile:
        csvReader = csv.reader(inputFile, skipinitialspace=True)
        for row in csvReader:
            vault: str = row[0].strip()
            createVaultWithName(vault)

            # If --remove-me flag was used, remove the script-runner's permission
            if args.removeMe:
                removeCreatorPermissionsFor(vault, myUUID)


main()
