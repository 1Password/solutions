import os
import subprocess
import json
import sys
import time
import argparse
import random

scriptPath = os.path.dirname(__file__)

parser = argparse.ArgumentParser(
    "Grant or revoke 'manage_vault' permission for the Administrators group on all non-Private vaults."
)
parser.add_argument(
    "--grant",
    "-g",
    action="store_const",
    const="grant",
    default="revoke",
    dest="action",
    metavar="Grant",
)


args = parser.parse_args()

action = args.action


# Get the User UUID of the person running the script. This is required for other parts of the script.
def getUUIDForGroup(groupName):
    print(
        f"Ensuring you're signed into 1Password and obtaining UUID for {groupName} group.\n"
    )
    r = subprocess.run(
        ["op", "group", "get", groupName, "--format=json"], capture_output=True
    )
    if r.returncode != 0:
        sys.exit(
            f"🔴 Unable to get your user UUID. Make sure you are are signed into the 1Password CLI. Error: {r.stderr.decode('utf-8')}"
        )
    print(f"🟢 Obtained UUID for {groupName}: {json.loads(r.stdout)['id']} \n")
    return json.loads(r.stdout)["id"]


# get a list of vaults the logged-in user has access to
def getAllOwnerVaults():
    return subprocess.run(
        ["op", "vault", "list", f"--group=Owners", "--format=json"],
        check=True,
        capture_output=True,
    ).stdout


# modifies the specified vault permissions from the group
def modifyGroupPermissions(vault, groupUUID):

    r = subprocess.run(
        [
            "op",
            "vault",
            "group",
            action,
            f"--vault={vault['id']}",
            f"--group={groupUUID}",
            f"--permissions=manage_vault",
            "--no-input",
        ],
        capture_output=True,
    )
    return r


def main():
    counter = 0
    print(
        f"Proceeding to {action} the 'manage_vault' permission for the Administrators group on all non-Private vaults."
    )
    adminGroupUUID = getUUIDForGroup("Administrators")
    accountVaults = json.loads(getAllOwnerVaults())
    vaultCount = len(accountVaults)
    print(f"Preparing to process {vaultCount} vaults.")
    for vault in accountVaults:
        noise = random.randrange(2, 4)
        counter += 1
        # skip your own Private vault and Private vaults of pending users
        if "Private Vault" in vault["name"] or vault["name"] == "Private":
            print(
                f"\n🔃 {counter}/{vaultCount} Skipping vault {vault['name']} because it is a Private vault"
            )
            continue

        if vault["name"] == "❗️ LastPass Imported Shared Folders Metadata":
            print(
                f"\n🔃 {counter}/{vaultCount} Skipping vault {vault['name']} because it is the LastPass Metadata Vault"
            )
            continue

        print(
            f"\n⌛ {counter}/{vaultCount} - Attempting to modify permissions for vault \"{vault['name']}\", with the UUID {vault['id']}."
        )
        retries = 0
        maxRetries = 3
        while retries < maxRetries:
            result = modifyGroupPermissions(vault, adminGroupUUID)
            if noise == 3:
                result.returncode = 429
            # Handle rate limit error
            if result.returncode == 429:
                # Retry after waiting for 3 seconds
                print(
                    f"\t🟡 Hit rate limit. Retrying in a few seconds. {maxRetries-retries} retries left before skipping."
                )
                time.sleep(3)
                retries += 1
                continue
            # Handle all other errors.
            elif result.returncode != 0:
                print(
                    f"\t❌ Unable to modify permissions on vault {vault['name']} with UUID {vault['id']}. Error: {result.stderr}"
                )
                break

            # Success
            print(
                f"\t🟢 Manage Vault permission successfully {action} to the Administrators group for vault {vault['name']} with UUID {vault['id']}"
            )
            break
        continue


main()
