# A script that provides a list of users and the names of every item contained in a list of vaultUUIDs
import os
import sys
import subprocess
import csv
import json
import argparse

parser = argparse.ArgumentParser(
    "User and Items Report Generator",
    "Generates a csv-like report listing all item names and UUIDs and all users who have access to each vault passed to this script.",
)
parser.add_argument(
    "--file",
    action="store",
    dest="filepath",
    help="Specify a path to a file containing a line-deliminted list of vault UUIDs to include in the report.",
)
args = parser.parse_args()

scriptPath = os.path.dirname(__file__)
inputFilePath = args.filepath
outputPath = scriptPath  # Optionally choose an alternative output path here.


# Check CLI version
def checkCLIVersion():
    r = subprocess.run(["op", "--version", "--format=json"], capture_output=True)
    major, minor = r.stdout.decode("utf-8").rstrip().split(".", 2)[:2]
    if not major == 2 and not int(minor) >= 25:
        sys.exit(
            "❌ You must be using version 2.25 or greater of the 1Password CLI. Please visit https://developer.1password.com/docs/cli/get-started to download the lastest version."
        )


# get the UUID of the user running the CLI script for use elsewhere in the script.
def getMyUUID():
    subprocess.run(["op signin"], shell=True, check=True)
    return json.loads(
        subprocess.run(
            ["op whoami --format=json"], check=True, shell=True, capture_output=True
        ).stdout
    )["user_uuid"]


try:
    myUUID = getMyUUID()
except Exception as e:
    sys.exit(
        "Unable to get your UUID. Please ensure you are signed into 1Password and try again."
    )


# get a list of vaults the logged-in user has access to
def getAllOwnerVaults():
    vaultList = subprocess.run(
        ["op", "vault", "list", "--permission=manage_vault", "--format=json"],
        check=True,
        capture_output=True,
    ).stdout
    return vaultList


def getSpecifiedVaults():
    with open(inputFilePath, "r", encoding="utf-8") as f:
        vaultList = []
        for id in f:
            vaultList.append(
                json.loads(
                    subprocess.run(
                        ["op", "vault", "get", id.rstrip(), "--format=json"],
                        check=True,
                        capture_output=True,
                    ).stdout
                )
            )
    return vaultList


# get a list of users and their permissions for a vault
def getVaultUserList(vaultID):
    vaultUserList = subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"],
        check=True,
        capture_output=True,
    ).stdout
    return vaultUserList


def getVaultItems(vaultID):
    vaultItemList = subprocess.run(
        f"op item list --vault={vaultID} --format=json",
        shell=True,
        check=True,
        capture_output=True,
    ).stdout
    return vaultItemList


# check the Owner's permissions for a vault. Add View Item permission if not granted
def addViewPermissions(vaultUserData, vaultUUID):
    myData = next((user for user in vaultUserData if user["id"] == myUUID), None)
    if myData is None:
        subprocess.run(
            [
                f"op vault user grant --user={myUUID} --vault={vaultUUID} --permissions=view_items"
            ],
            shell=True,
            check=True,
            capture_output=True,
        )
        print(f"View permission for {vaultUUID} granted")
        return True
    elif myData is not None:
        permissions = myData["permissions"]
        if "view_items" not in permissions:
            subprocess.run(
                [
                    f"op vault user grant --user={myUUID} --vault={vaultUUID} --permissions=view_items"
                ],
                shell=True,
                check=True,
                capture_output=True,
            )
            print(f"view permission for {vaultUUID} granted")
            return True
    else:
        return


# remove the View Item permission.
def removeViewPermissions(vaultUserData, vaultUUID):
    myData = next((user for user in vaultUserData if user["id"] == myUUID), None)
    if myData is None:
        subprocess.run(
            [
                f"op vault user revoke --user={myUUID} --vault={vaultUUID} --permissions=view_items"
            ],
            shell=True,
            check=True,
            capture_output=True,
        )
        print(f"View permission for vault {vaultUUID} revoked")
    elif myData is not None:
        permissions = myData["permissions"]
        if "view_items" not in permissions:
            subprocess.run(
                [
                    f"op vault user revoke --user={myUUID} --vault={vaultUUID} --permissions=view_items"
                ],
                shell=True,
                check=True,
                capture_output=True,
            )
            print(f"View permission for vault {vaultUUID} revoked")


def main():
    checkCLIVersion()
    if inputFilePath is None:
        try:
            vaultList = json.loads(getAllOwnerVaults())
        except Exception as e:
            sys.exit(
                "Unable to get a list of vaults for the Owner group. Please sign into 1Password as a member of the Owners group or provide a list of vault UUIDs using the --file option."
            )
    else:
        vaultList = getSpecifiedVaults()

    with open(f"{outputPath}/vault-item-report.csv", "w", newline="") as outputFile:
        csvWriter = csv.writer(outputFile)
        fields = [
            "vaultName",
            "vaultUUD",
            "userName",
            "userEmail",
            "userUUID",
            "userPermissions",
            "itemName",
            "itemUUID",
            "itemUsername",
            "itemUrl",
        ]
        csvWriter.writerow(fields)

        for vault in vaultList:
            permissionsModified = False
            if (
                "Private Vault" in vault["name"] or vault["name"] == "Private"
            ):  # skip your own Private vault and Private vaults of pending users
                continue
            vaultUserList = json.loads(getVaultUserList(vault["id"]))
            permissionsModified = addViewPermissions(vaultUserList, vault["id"])

            try:
                itemList = json.loads(getVaultItems(vault["id"]))
            except Exception as e:
                print(
                    f"ERR: Unable to list items in vault {vault['id']}. It's possible the 1Password CLI has been removed from the 'App Access' list for this vault. Error: ",
                    e,
                )
                continue

            csvWriter.writerow(
                [
                    vault["name"],
                    vault["id"],
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ]
            )
            print(vault["name"], vault["id"])

            for user in vaultUserList:
                csvWriter.writerow(
                    [
                        None,
                        None,
                        user["name"],
                        user["email"],
                        user["id"],
                        user["permissions"],
                        None,
                        None,
                    ]
                )
                print(user["name"], user["email"], user["id"], user["permissions"])

            for item in itemList:
                username = ""
                if item["category"] == "LOGIN":
                    username = (
                        item["additional_information"]
                        if item.get("additional_information")
                        else ""
                    )
                website = ""
                if item.get("urls"):
                    website = next(
                        (
                            itemURL["href"]
                            for itemURL in item["urls"]
                            if itemURL["primary"] == True
                        ),
                        "",
                    )
                csvWriter.writerow(
                    [
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        item["title"],
                        item["id"],
                        username,
                        website,
                    ]
                )
                print(item["title"], item["id"], username, website)
            if (
                permissionsModified == True
            ):  # if permission was added, remove the permission
                removeViewPermissions(vaultUserList, vault["id"])


main()


# {
#   "id": "c4qkveam5ctkjujsm5vluynkc4",
#   "title": "testLogin",
#   "version": 1,
#   "vault": {
#     "id": "g6ry6knpuqcryb4ap2hcexwhwm",
#     "name": "Employee"
#   },
#   "category": "LOGIN",
#   "last_edited_by": "LYNHQG2JGRFV3JMLVKHQWTLNR4",
#   "created_at": "2024-11-29T19:25:37Z",
#   "updated_at": "2024-11-29T19:25:37Z",
#   "additional_information": "scott@scottlougheed.com",
#   "fields": [
#     {
#       "id": "username",
#       "type": "STRING",
#       "purpose": "USERNAME",
#       "label": "username",
#       "value": "scott@scottlougheed.com",
#       "reference": "op://Employee/testLogin/username"
#     },
#     {
#       "id": "password",
#       "type": "CONCEALED",
#       "purpose": "PASSWORD",
#       "label": "password",
#       "value": "f3RFbUB2jV.QVx8HBbP.sCWVu.Ensej-",
#       "entropy": 189.70021057128906,
#       "reference": "op://Employee/testLogin/password",
#       "password_details": {
#         "entropy": 189,
#         "generated": true,
#         "strength": "FANTASTIC",
#         "history": ["eLzQGppXLbz2BfwEPEew"]
#       }
#     },
#     {
#       "id": "notesPlain",
#       "type": "STRING",
#       "purpose": "NOTES",
#       "label": "notesPlain",
#       "reference": "op://Employee/testLogin/notesPlain"
#     }
#   ]
# }
