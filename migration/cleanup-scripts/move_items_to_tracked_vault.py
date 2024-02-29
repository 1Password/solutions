#!/usr/bin/python3
import json
import os
import subprocess
import sys

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath  # Optionally choose an alternative output path here.


class Vault:
    def __init__(self, name, uuid, itemCount, created, updated):
        self.name = name
        self.uuid = uuid
        self.itemCount = itemCount
        self.created = created
        self.updated = updated


# Check CLI version
def checkCLIVersion():
    r = subprocess.run(["op", "--version", "--format=json"], capture_output=True)
    major, minor = r.stdout.decode("utf-8").rstrip().split(".", 2)[:2]
    if not major == 2 and not int(minor) >= 25:
        sys.exit(
            "❌ You must be using version 2.25 or greater of the 1Password CLI. Please visit https://developer.1password.com/docs/cli/get-started to download the lastest version."
        )


# Get a list of vaults the logged-in user has access to
# Skips any Private vaults and the Metadata vault.
# Fetches all vault details and returns them as a Python object
def getOwnerGroupUUID():
    results = subprocess.run(
        ["op", "group", "get", "Owners", "--format=json"],
        capture_output=True,
        check=True,
    )
    if results.returncode != 0:
        sys.exit(
            "Unable to get the UUID of the Owners group. Ensure you are signed into 1Password and are a member of the Owners group."
        )
    return json.loads(results.stdout)["id"]


def getVaults():
    vaults = []
    try:
        getVaultsCommand = subprocess.run(
            ["op", "vault", "list", "--permission=manage_vault", "--format=json"],
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
            if len(processResults.stderr) > 0:
                print(
                    f"encountered an error getting details of a vault: {str(processResults.stderr)}"
                )
                continue
            vaults.append(json.loads(processResults.stdout))
        return vaults
    except Exception as err:
        print(
            f"Encountered an error getting the list of vaults you have access to: {err}"
        )
        return


# From a list of vaults within a group of identically-named vaults
def identifyTrackedVault(vaultGroupName, vaults):
    print(
        "\tIdentifying tracked, data, and other duplicates for vault group:",
        vaultGroupName,
    )

    # Sort by item count to facilitate identifying tracked and data vaults
    vaults.sort(key=lambda vault: vault.itemCount)

    # Identity vault with greatest number of items, assumption being it has canonical data
    dataVault = vaults[0]

    # Identify vault with zero items, assumption is that is tracked by metadata vault
    trackedVault = vaults[-1]

    # triplicates or greater that are not data or tracked
    otherVaults = vaults[1:-1]

    return dataVault, trackedVault, otherVaults


def getOwnerPermissions(vaultID, ownerID):
    groupListResults = subprocess.run(
        [
            "op",
            "vault",
            "group",
            "list",
            f"{vaultID}",
            "--format=json",
        ],
        capture_output=True,
    )
    if groupListResults.returncode != 0:
        print(
            f"\t⚠️ Unable to get a list of groups with access to vault with UUID {vaultID} and cannot record Owner's permissions."
        )
    jsonData = json.loads(groupListResults.stdout)
    ownerDetails = [group for group in jsonData if group["id"] == ownerID]
    ownerPermissions = ",".join(ownerDetails[0]["permissions"])
    return ownerPermissions


def grantOwnerPermissions(vaultID):
    ownerPermissions = "view_items,create_items,edit_items,archive_items,delete_items,view_and_copy_passwords,view_item_history,import_items,export_items,copy_and_share_items,print_items,manage_vault"
    print(f"\tUpdating permissions on duplicate vault with UUID: {vaultID}")
    results = subprocess.run(
        [
            "op",
            "vault",
            "group",
            "grant",
            f"--vault={vaultID}",
            f"--group=Owners",
            f"--permissions={ownerPermissions}",
            "--no-input",
        ],
        capture_output=True,
    )
    if results.returncode != 0:
        print(
            f"⚠️ Unable to set Owner permissions on vault with UUID: {vaultID}. Error: {results.stderr}"
        )


def resetOwnerPermissions(trackedVault, ownerPermissions):
    allPermissions = "view_items,create_items,edit_items,archive_items,delete_items,view_and_copy_passwords,view_item_history,import_items,export_items,copy_and_share_items,print_items,manage_vault"
    print(
        f"\tResetting owner permissions on tracked vault with UUID: {trackedVault.uuid}"
    )
    subprocess.run(
        [
            "op",
            "vault",
            "group",
            "revoke",
            f"--vault={trackedVault.uuid}",
            f"--group=Owners",
            f"--permissions={allPermissions}",
            "--no-input",
        ],
        capture_output=True,
    )
    results = subprocess.run(
        [
            "op",
            "vault",
            "group",
            "grant",
            f"--vault={trackedVault.uuid}",
            f"--group=Owners",
            f"--permissions={ownerPermissions}",
            "--no-input",
        ],
        capture_output=True,
    )
    if results.returncode != 0:
        print(
            f"⚠️ Unable to reset Owner permissions on vault with UUID: {trackedVault.uuid}. Error: {results.stderr}"
        )


def getVaultItems(vaultID):
    print(
        f"\tGetting vault items for vault with UUID: {vaultID}. This may take a while."
    )
    try:
        return subprocess.run(
            ["op", "item", "list", f"--vault={vaultID}", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(f"Encountered an error getting items for vault {vaultID}: {err}")
        return


# Move items from data vault to tracked vault.
def moveItemsToTrackedVault(trackedVault, dataVault):
    items = json.loads(getVaultItems(dataVault.uuid))
    print(
        f"\tMoving items from data vault with UUID: {dataVault.uuid} to tracked vault with UUID: {trackedVault.uuid}. This may take a while."
    )
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
            print(
                f"\tMoved item named `{item['title']}` from vault with UUID: {dataVault.uuid} to vault with UUID: {trackedVault.uuid}."
            )
            if len(moveCmd.stderr) > 0:
                print(
                    f"⚠️ error moving the item with title `{item['title']}` from vault with UUID: {dataVault.uuid} to vault with UUID: {trackedVault.uuid}.",
                    moveCmd.stderr,
                )
        except Exception as err:
            print(
                f"\tUnable to move item with name '{item['title']}' and ID of '{item['id']}' with error: {err}"
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
        print(f"\tRENAME untracked vaults result \n\t{renameCmd}")
        suffix += 1


# revoke all access and permissions from untracked vaults
def revokeUntrackedVaultPermissions(untrackedVaults):
    permissions = "view_items,create_items,edit_items,archive_items,delete_items,view_and_copy_passwords,view_item_history,import_items,export_items,copy_and_share_items,print_items,manage_vault"
    for vault in untrackedVaults:
        print(f"\tModifying permissions for vault '{vault.name}', UUID: {vault.uuid}.")
        allgroups = json.loads(
            subprocess.run(
                ["op", "vault", "group", "list", vault.uuid, "--format=json"],
                capture_output=True,
                text=True,
            ).stdout
        )
        allUsers = json.loads(
            subprocess.run(
                ["op", "vault", "user", "list", vault.uuid, "--format=json"],
                capture_output=True,
                text=True,
            ).stdout
        )

        for group in allgroups:
            print(
                f"\tRevoking group '{group['name']}' permissions for vault '{vault.name}', UUID: {vault.uuid}"
            )
            groupRevokeCmd = subprocess.run(
                [
                    "op",
                    "vault",
                    "group",
                    "revoke",
                    f"--vault={vault.uuid}",
                    f"--group={group['id']}",
                    f"--permissions={permissions}",
                    "--no-input",
                ],
                capture_output=True,
            )
            if len(groupRevokeCmd.stderr) > 0:
                print(f"ERROR: {groupRevokeCmd.stderr}")

        for user in allUsers:
            print(
                f"\tRevoking user '{str(user['name'])}' permissions for vault '{vault.name}', UUID: {vault.uuid}"
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
            if len(userRevokeCmd.stderr) > 0:
                print(f"ERROR! {str(userRevokeCmd.stderr)}")


def main():
    checkCLIVersion()
    vaults = []
    vaultGroups = {}
    vaultDetails = getVaults()
    ownerGroupUUID = getOwnerGroupUUID()

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

    # Ensure vaults are alpha sorted to make grouping duplicates easier and more reliable
    vaults.sort(key=lambda vault: vault.name)

    # Create a dict containing groups of identically-named vaults.
    # Dict keys are a vault name representing all vaults with that name.
    # The value for each key is a list of Vault class instances with that name,
    # forming a vault group.
    for vault in vaults:
        if vault.name not in vaultGroups:
            vaultGroups[vault.name] = []
        vaultGroups[vault.name].append(vault)

    for vaultGroupName, vaults in vaultGroups.items():
        ownerPermissionsTracked = ""
        if len(vaults) == 1:
            print(
                f"Vault with name '{vaultGroupName}' is unique. Skipping de-duplication."
            )
            continue
        print("Processing vault group:", vaultGroupName)
        print(
            f"\tGranting Owners group required permissions for vault named '{vaultGroupName}'"
        )
        trackedVault, dataVault, otherVaults = identifyTrackedVault(
            vaultGroupName, vaults
        )
        ownerPermissionsTracked = getOwnerPermissions(trackedVault.uuid, ownerGroupUUID)
        for vault in vaults:
            grantOwnerPermissions(vault.uuid)

        otherVaultNames = "none"
        if len(otherVaults) > 0:
            otherVaultNames = ""
            for vault in otherVaults:
                otherVaultNames += f"{vault.name}, Items: {vault.itemCount}"

        print(
            f"\tTRACKED VAULT: '{trackedVault.name}' containing: {trackedVault.itemCount} items. \n\tDATA VAULT: '{dataVault.name}' containing {dataVault.itemCount} items. \n\tOTHER VAULTS: {otherVaultNames}."
        )
        moveItemsToTrackedVault(trackedVault, dataVault)
        untrackedVaults = otherVaults
        untrackedVaults.append(dataVault)
        renameUntrackedVaults(untrackedVaults)
        resetOwnerPermissions(trackedVault, ownerPermissionsTracked)
        revokeUntrackedVaultPermissions(untrackedVaults)


main()
