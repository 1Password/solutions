import os
import subprocess
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

scriptPath = os.path.dirname(__file__)
outputPath = scriptPath

print("🚀 Starting vault access report for all active users (excluding 'Automated User Provisioning')")

class Vault:
    vaults = []

    def __init__(self, name, uuid, users=None, groups=None):
        self.name = name
        self.uuid = uuid  # Still needed internally for API calls
        self.users = []
        self.groups = []
        Vault.vaults.append(self)

    def addUser(self, user):
        self.users.append(user)

    @classmethod
    def getAll(cls):
        return [inst for inst in cls.vaults]

    @classmethod
    def getByID(cls, vaultID):
        for vault in cls.vaults:
            if vault.uuid == vaultID:
                return vault

def checkCLIVersion():
    print("🔍 Checking 1Password CLI version...")
    r = subprocess.run(["op", "--version", "--format=json"], capture_output=True)
    major, minor = r.stdout.decode("utf-8").rstrip().split(".", 2)[:2]
    print(f"CLI version: {major}.{minor}")
    if not (major == "2" and int(minor) >= 25):
        sys.exit(
            "❌ You must be using version 2.25 or greater of the 1Password CLI. Please visit https://developer.1password.com/docs/cli/get-started to download the latest version."
        )
    print("✅ CLI version check passed.\n")

def getAllOwnerVaults():
    print("📥 Fetching all owner vaults...")
    try:
        vaultList = subprocess.run(
            ["op", "vault", "list", "--permission=manage_vault", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
        vaults = json.loads(vaultList)
        skipped = 0
        for vault in vaults:
            vault_name = vault["name"]
            if vault_name.lower() == "employee":
                skipped += 1
                continue
            Vault(
                name=vault_name,
                uuid=vault["id"],
            )
        print(f"Found {len(vaults)} vaults total. Processed {len(Vault.vaults)} after skipping {skipped} employee-related vaults.\n")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error fetching owner vaults: {e}")
        sys.exit(f"Unable to get a list of vaults for the Owner group. Error: {e}")

def getVaultUserList(vaultID):
    try:
        vaultUserList = subprocess.run(
            ["op", "vault", "user", "list", vaultID, "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
        return vaultUserList.decode('utf-8')
    except subprocess.CalledProcessError as e:
        print(f"❌ Error fetching users for vault ID {vaultID}: {e}")
        return "[]"

def getVaultGroupList(vaultID):
    try:
        vaultGroupList = subprocess.run(
            ["op", "vault", "group", "list", vaultID, "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
        return vaultGroupList.decode('utf-8')
    except subprocess.CalledProcessError as e:
        print(f"❌ Error fetching groups for vault ID {vaultID}: {e}")
        return "[]"

def getGroupMembers(groupID):
    try:
        groupMembers = subprocess.run(
            ["op", "group", "user", "list", groupID, "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
        return groupMembers.decode('utf-8')
    except subprocess.CalledProcessError as e:
        print(f"❌ Error fetching members for group ID {groupID}: {e}")
        return "[]"

def getAllUsers():
    print("👥 Fetching all users...")
    try:
        userList = subprocess.run(
            ["op", "user", "list", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
        all_users = json.loads(userList)
        active_users = [user for user in all_users if user["state"] == "ACTIVE" and user["name"] != "Automated User Provisioning"]
        print(f"Found {len(active_users)} active users (excluding 'Automated User Provisioning')\n")
        return active_users
    except subprocess.CalledProcessError as e:
        print(f"❌ Error fetching users: {e}")
        sys.exit(f"Unable to get list of users. Error: {e}")

def writeReport(vaults):
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    output_file = f"{outputPath}/vaultAccessReport_{timestamp}.csv"
    try:
        with open(output_file, "w", newline="") as outputFile:
            csvWriter = csv.writer(outputFile)
            fields = [
                "vaultName",
                "email",
                "assignment",
                "permissions",
            ]
            csvWriter.writerow(fields)
            entries_written = 0
            for vault in vaults:
                vaultName = vault.name
                for user in vault.users:
                    csvWriter.writerow(
                        [
                            vaultName,
                            user["email"],
                            user["assignment"],
                            user["permissions"],
                        ]
                    )
                    entries_written += 1
            if entries_written == 0:
                print("⚠️ No vault assignments found for any active users")
            else:
                print(f"✍️ Wrote {entries_written} entries to report\n")
        print(f"🎉 Report generated: {output_file}\n")
        return output_file
    except Exception as e:
        print(f"❌ Error writing report: {e}")
        sys.exit(f"Unable to write data to a file on disk. Error: {e}")

def main():
    checkCLIVersion()
    try:
        getAllOwnerVaults()
    except Exception as e:
        print(f"❌ Error fetching owner vaults: {e}")
        sys.exit(
            "Unable to get a list of vaults for the Owner group. Please sign into 1Password as a member of the Owners group. Error: ",
            e,
        )

    vaults = Vault.getAll()
    vaultCount = len(vaults)
    print(f"🏦 Total vaults to process: {vaultCount}\n")

    # Get all active users
    active_users = getAllUsers()

    with ThreadPoolExecutor() as executor:
        print("🔗 Processing direct vault assignments...")
        user_futures = {executor.submit(getVaultUserList, vault.uuid): vault for vault in vaults}
        for future in as_completed(user_futures):
            vault = user_futures[future]
            try:
                users = json.loads(future.result())
                for user in users:
                    if user["state"] == "ACTIVE" and user["name"] != "Automated User Provisioning":
                        vault.users.append(
                            {
                                "email": user["email"],
                                "assignment": "Direct",
                                "permissions": user["permissions"],
                            }
                        )
            except Exception as e:
                print(f"❌ Error processing users for vault {vault.name}: {e}")
                sys.exit(
                    f"Unable to get a list of users directly assigned to vault {vault.name}. Error: {e}"
                )
        print("✅ Direct vault assignments processed.\n")

        print("👥 Processing vault group assignments...")
        group_futures = {executor.submit(getVaultGroupList, vault.uuid): vault for vault in vaults}
        group_data = []
        for future in as_completed(group_futures):
            vault = group_futures[future]
            try:
                groups = json.loads(future.result())
                for group in groups:
                    vault.groups.append(
                        {
                            "name": group["name"],
                            "permissions": group["permissions"],
                        }
                    )
                    group_data.append((vault, group["id"], group["name"], group["permissions"]))
            except Exception as e:
                print(f"❌ Error processing groups for vault {vault.name}: {e}")
                sys.exit(
                    f"Unable to get a list of groups assigned to vault {vault.name}. Error: {e}"
                )
        print("✅ Vault group assignments processed.\n")

        print("🔄 Processing user vault access through groups...")
        group_member_futures = {executor.submit(getGroupMembers, group_id): (vault, group_id, group_name, permissions) 
                              for vault, group_id, group_name, permissions in group_data}
        for future in as_completed(group_member_futures):
            vault, group_id, group_name, permissions = group_member_futures[future]
            try:
                groupUsers = json.loads(future.result())
                if groupUsers is not None:
                    for groupUser in groupUsers:
                        if groupUser["state"] == "ACTIVE" and groupUser["name"] != "Automated User Provisioning":
                            vault.users.append(
                                {
                                    "email": groupUser["email"],
                                    "assignment": f'Group ({group_name})',
                                    "permissions": permissions,
                                }
                            )
            except Exception as e:
                print(f"❌ Error processing group members for group {group_name} in vault {vault.name}: {e}")
                sys.exit(
                    f"Unable to get a list of group members in group {group_name} assigned to vault {vault.name}. Error: {e}"
                )
        print("✅ User vault access through groups processed.\n")

    try:
        print("📊 Generating report...\n")
        output_file = writeReport(vaults)
    except Exception as e:
        print(f"❌ Error writing report: {e}")
        sys.exit(f"Unable to write data to a file on disk. Error: {e}")

if __name__ == "__main__":
    main()