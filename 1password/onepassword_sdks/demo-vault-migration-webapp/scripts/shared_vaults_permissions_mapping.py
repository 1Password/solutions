import os
import subprocess
import csv
import json
import argparse
import sys
import concurrent.futures
from functools import lru_cache
import gc
import time

MAX_WORKERS = 10
EXCLUDED_VAULTS = {"Employee"}

parser = argparse.ArgumentParser(
    description="Generate a CSV report of vault user permissions and assignments."
)
parser.add_argument(
    "--file",
    dest="filepath",
    help="Path to a file with line-delimited vault UUIDs."
)
args = parser.parse_args()

script_dir = os.path.dirname(__file__)
input_file = args.filepath
output_dir = script_dir

class Vault:
    vaults = []

    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid
        self.users = []
        self.groups = []
        Vault.vaults.append(self)

    @classmethod
    def all(cls):
        return cls.vaults

    @classmethod
    def clear(cls):
        cls.vaults = []
        gc.collect()

def check_cli_version() -> None:
    try:
        result = subprocess.run(
            ["op", "--version", "--format=json"],
            capture_output=True,
            text=True,
            check=True
        )
        major, minor = result.stdout.rstrip().split(".", 2)[:2]
        if major != "2" or int(minor) < 25:
            sys.exit("Requires 1Password CLI v2.25 or higher. See https://developer.1password.com/docs/cli/get-started.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Failed to check CLI version: {e}")

def load_owner_vaults() -> None:
    try:
        vaults = json.loads(subprocess.run(
            ["op", "vault", "list", "--permission=manage_vault", "--format=json"],
            check=True,
            capture_output=True,
            text=True
        ).stdout)
        for vault in vaults:
            if vault["name"] not in EXCLUDED_VAULTS:
                Vault(vault["name"], vault["id"])
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        sys.exit(f"Failed to load owner vaults: {e}")

def load_specified_vaults() -> None:
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            for uuid in f:
                vault = json.loads(subprocess.run(
                    ["op", "vault", "get", uuid.rstrip(), "--format=json"],
                    check=True,
                    capture_output=True,
                    text=True
                ).stdout)
                if vault["name"] not in EXCLUDED_VAULTS:
                    Vault(vault["name"], vault["id"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
        sys.exit(f"Failed to load specified vaults: {e}")

@lru_cache(maxsize=128)
def get_vault_users(vault_id: str) -> str:
    try:
        return subprocess.run(
            ["op", "vault", "user", "list", vault_id, "--format=json"],
            check=True,
            capture_output=True,
            text=True
        ).stdout
    except subprocess.CalledProcessError:
        return json.dumps([])

@lru_cache(maxsize=128)
def get_vault_groups(vault_id: str) -> str:
    try:
        return subprocess.run(
            ["op", "vault", "group", "list", vault_id, "--format=json"],
            check=True,
            capture_output=True,
            text=True
        ).stdout
    except subprocess.CalledProcessError:
        return json.dumps([])

@lru_cache(maxsize=128)
def get_group_members(group_id: str) -> str:
    try:
        return subprocess.run(
            ["op", "group", "user", "list", group_id, "--format=json"],
            check=True,
            capture_output=True,
            text=True
        ).stdout
    except subprocess.CalledProcessError:
        return json.dumps([])

def print_progress(completed: int, total: int, start_time: float) -> None:
    percent = completed / total
    bar_width = 40
    filled = int(bar_width * percent)
    bar = "█" * filled + "─" * (bar_width - filled)
    elapsed = time.time() - start_time
    eta = (elapsed / completed * (total - completed)) if completed > 0 else 0
    print(f"\rProcessing vaults: [{bar}] {completed}/{total} ({percent:.0%})  ETA: {eta:.0f}s", end="", flush=True)

def process_vault(vault: Vault) -> tuple[float, str]:
    start = time.time()
    try:
        # Direct user assignments
        users = json.loads(get_vault_users(vault.uuid))
        for user in users:
            vault.users.append({
                "name": user["name"],
                "email": user["email"],
                "uuid": user["id"],
                "assignment": "Direct",
                "state": user["state"],
                "permissions": user["permissions"]
            })

        # Group assignments
        groups = json.loads(get_vault_groups(vault.uuid))
        for group in groups:
            vault.groups.append({
                "name": group["name"],
                "groupUUID": group["id"],
                "permissions": group["permissions"]
            })
            members = json.loads(get_group_members(group["id"]))
            for member in members:
                vault.users.append({
                    "name": member["name"],
                    "email": member["email"],
                    "uuid": member["id"],
                    "groupName": group["name"],
                    "assignment": f"Group ({group['name']})",
                    "state": member["state"],
                    "permissions": group["permissions"]
                })

        return time.time() - start, f"Processed vault '{vault.name}' in {{:.2f}} seconds"
    except (json.JSONDecodeError, KeyError) as e:
        return time.time() - start, f"Error processing vault {vault.name}: {e}"

def write_report(vaults: list[Vault]) -> None:
    try:
        with open(f"{output_dir}/vault_access_report.csv", "w", newline="") as f:
            writer = csv.writer(f)
            fields = [
                "vaultName", "vaultUUID", "userName", "groupName",
                "email", "userUUID", "assignment", "status", "permissions"
            ]
            writer.writerow(fields)
            for vault in vaults:
                for user in vault.users:
                    writer.writerow([
                        vault.name, vault.uuid, user["name"],
                        user.get("groupName"), user["email"], user["uuid"],
                        user["assignment"], user["state"], user["permissions"]
                    ])
    except IOError as e:
        sys.exit(f"Failed to write report: {e}")

def main() -> None:
    start = time.time()
    check_cli_version()

    try:
        if input_file:
            load_specified_vaults()
        else:
            load_owner_vaults()
    except Exception as e:
        sys.exit(f"Failed to load vaults: {e}")

    vaults = Vault.all()
    if not vaults:
        print("No vaults to process.")
        return

    total = len(vaults)
    completed = 0
    print(f"Processing {total} vaults with {MAX_WORKERS} threads...")
    print_progress(0, total, start)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_vault, v): v for v in vaults}
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            print_progress(completed, total, start)

    print()  # newline after progress bar

    write_report(vaults)
    print(f"\nReport generated at {output_dir}/vault_access_report.csv")

    Vault.clear()
    get_vault_users.cache_clear()
    get_vault_groups.cache_clear()
    get_group_members.cache_clear()
    gc.collect()

if __name__ == "__main__":
    main()