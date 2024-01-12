import os
import subprocess
import json
import sys
import argparse


scriptPath = os.path.dirname(__file__)


parser = argparse.ArgumentParser(
    "Bulk-revoke permissions.",
    "Revoke one or more specified permissions from all users and groups for all vaults the person running the script can access. ",
)
parser.add_argument(
    "--as-admin",
    action="store_true",
    dest="isAdmin",
    help="Set this flag if you are running this script as a member of the Administrators group.",
)
parser.add_argument(
    "--permissions",
    "-p",
    action="store",
    dest="permissions",
    help=f"Provide a comma-seprated list of permissions to revoke using the following permission names: view_items, create_items, edit_items, archive_items, delete_items, view_and_copy_passwords, view_item_history, import_items, export_items, copy_and_share_items, print_items, manage_vault",
)
args = parser.parse_args()

if args.isAdmin:
    userGroup = "Administrators"
else:
    userGroup = "Owners"

permissions = args.permissions


# get a list of vaults the logged-in user has access to
def getAllOwnerVaults():
    return subprocess.run(
        ["op", "vault", "list", f"--group={userGroup}", "--format=json"],
        check=True,
        capture_output=True,
    ).stdout


# Gets a list of all vaults the Owner has Manage Vault permissions on
def getVaultUserList(vaultID):
    return subprocess.run(
        ["op", "vault", "user", "list", vaultID, "--format=json"],
        check=True,
        capture_output=True,
    ).stdout


# get all groups that have access to the specified vault, excluding Owners and Administrators group
def getVaultGroupList(vaultUUID):
    allgroups = subprocess.run(
        ["op", "vault", "group", "list", vaultUUID, "--format=json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return allgroups


# revokes the specified vault permissions from the grou
def revokeGroupPermissions(vaultUUID, groupUUID):
    subprocess.run(
        [
            "op",
            "vault",
            "group",
            "revoke",
            f"--vault={vaultUUID}",
            f"--group={groupUUID}",
            f"--permissions={permissions}",
            "--no-input",
        ]
    )


# revokes the specified vault permissions from the grou
def revokeUserPermissions(vaultUUID, userUUID):
    subprocess.run(
        [
            "op",
            "vault",
            "user",
            "revoke",
            f"--vault={vaultUUID}",
            f"--user={userUUID}",
            f"--permissions={permissions}",
            "--no-input",
        ]
    )


def main():
    if permissions is None:
        sys.exit(
            "Please provide a list of permissions with --permissions=PERMISSIONS and run the script again"
        )

    accountVaults = json.loads(getAllOwnerVaults())

    for vault in accountVaults:
        print(f"HI! {vault['id']}")
        vaultGroups = json.loads(getVaultGroupList(vault["id"]))
        vaultUsers = json.loads(getVaultUserList(vault["id"]))
        print("VAULT GROUPS: ", vaultGroups)

        for group in vaultGroups:
            if group["name"] == "Administrators":
                print("ADMINISTRATOR")
            elif group["name"] == "Owners":
                print("OWNER")
            else:
                print("NEITHER OWNER NOR ADMIN: ", group["name"])
                revokeGroupPermissions(vault["id"], group["id"])

        for user in vaultUsers:
            revokeUserPermissions(vault["id"], user["id"])


main()
