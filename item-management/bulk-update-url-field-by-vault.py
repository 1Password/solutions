import subprocess
import json
import csv
import threading
import concurrent.futures
import sys
import itertools
import time
from datetime import datetime
import os
from typing import List, Dict, Optional
from tqdm import tqdm

# Script to update website fields for all items in a 1Password vault.
# Allows selecting a vault, setting a new URL, retrying if needed, or reverting changes.

# ANSI color codes for console output.
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

# Displays a table in a styled ASCII box with column separators.
def show_table_in_box(data: List[Dict[str, str]]) -> None:
    # Define column headers.
    headers = ["ItemID", "ItemTitle", "OldWebsite", "NewWebsite"]

    # Calculate maximum length for each column.
    max_lengths = {
        "ItemID": max(max(len(item["ItemID"]) for item in data), len("ItemID")),
        "ItemTitle": max(max(len(item["ItemTitle"]) for item in data), len("ItemTitle")),
        "OldWebsite": max(max(len(item["OldWebsite"]) for item in data), len("OldWebsite")),
        "NewWebsite": max(max(len(item["NewWebsite"]) for item in data), len("NewWebsite"))
    }

    # Add padding for readability.
    max_lengths = {k: v + 2 for k, v in max_lengths.items()}

    # Build the box borders.
    top_border = "┌" + "─" * max_lengths["ItemID"] + "┬" + "─" * max_lengths["ItemTitle"] + "┬" + "─" * max_lengths["OldWebsite"] + "┬" + "─" * max_lengths["NewWebsite"] + "┐"
    header_row = (
        "│ " + headers[0].ljust(max_lengths["ItemID"] - 2) + " │ " +
        headers[1].ljust(max_lengths["ItemTitle"] - 2) + " │ " +
        headers[2].ljust(max_lengths["OldWebsite"] - 2) + " │ " +
        headers[3].ljust(max_lengths["NewWebsite"] - 2) + " │"
    )
    mid_border = "├" + "─" * max_lengths["ItemID"] + "┼" + "─" * max_lengths["ItemTitle"] + "┼" + "─" * max_lengths["OldWebsite"] + "┼" + "─" * max_lengths["NewWebsite"] + "┤"
    bottom_border = "└" + "─" * max_lengths["ItemID"] + "┴" + "─" * max_lengths["ItemTitle"] + "┴" + "─" * max_lengths["OldWebsite"] + "┴" + "─" * max_lengths["NewWebsite"] + "┘"

    # Output the box.
    print(f"{CYAN}{top_border}{RESET}")
    print(f"{CYAN}{header_row}{RESET}")
    print(f"{CYAN}{mid_border}{RESET}")
    for item in data:
        item_id = item["ItemID"].ljust(max_lengths["ItemID"] - 2)
        item_title = item["ItemTitle"].ljust(max_lengths["ItemTitle"] - 2)
        old_website = item["OldWebsite"].ljust(max_lengths["OldWebsite"] - 2)
        new_website = item["NewWebsite"].ljust(max_lengths["NewWebsite"] - 2)
        print(f"│ {item_id} │ {item_title} │ {old_website} │ {new_website} │")
    print(f"{CYAN}{bottom_border}{RESET}")

# Executes a 1Password CLI command and returns the output.
def run_op_command(args: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(["op"] + args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return None

# Prompt the user to select a vault.
print(f"\n{CYAN}🚀 Starting website field update process...{RESET}")
vault = None
show_list_prompt = True
while not vault:
    print("")
    if show_list_prompt:
        print("Type the name or UUID of the vault, or press Enter to list all vaults:")
    else:
        print("Type the name or UUID of the vault:")
    vault_input = input(f"{YELLOW}➡️ Enter your choice: {RESET}").strip()

    # Exit if the user types 'quit' or 'exit'.
    if vault_input.lower() in ['quit', 'exit']:
        print(f"\n{YELLOW}🚫 Exiting the script.{RESET}")
        print("")
        sys.exit(0)

    # Display the list of vaults if the user presses Enter or types 'list'.
    if not vault_input or vault_input.lower() == 'list':
        vaults_json = run_op_command(["vault", "list", "--format=json"])
        if vaults_json:
            vaults = json.loads(vaults_json)
            print(f"\n{CYAN}📋 Available vaults:{RESET}")
            for v in vaults:
                print(f"  - {v['name']} (ID: {v['id']})")
        show_list_prompt = False
        continue

    # Check if the input matches a vault name or UUID.
    vaults_json = run_op_command(["vault", "list", "--format=json"])
    if vaults_json:
        vaults = json.loads(vaults_json)
        vault = next((v for v in vaults if v['name'] == vault_input or v['id'] == vault_input), None)
        if not vault:
            print(f"\n{RED}😕 Couldn't find a vault with name or UUID '{vault_input}'. Try again or press Enter to list all vaults!{RESET}")
            show_list_prompt = False

# Confirm the selected vault with the user.
vault_confirmed = False
while not vault_confirmed:
    print("")
    print(f"You picked the vault '{vault['name']}' (ID: {vault['id']}). Sound good? (y/n, Enter for y)")
    confirm_vault = input(f"{YELLOW}➡️ Enter your choice: {RESET}").strip()

    # Default to 'y' if Enter is pressed.
    if not confirm_vault:
        confirm_vault = 'y'

    if confirm_vault.lower() == 'y':
        vault_confirmed = True
    elif confirm_vault.lower() == 'n':
        vault = None
        show_list_prompt = True
        while not vault:
            print("")
            if show_list_prompt:
                print("Type the name or UUID of the vault, or press Enter to list all vaults:")
            else:
                print("Type the name or UUID of the vault:")
            vault_input = input(f"{YELLOW}➡️ Enter your choice: {RESET}").strip()

            # Exit if the user types 'quit' or 'exit'.
            if vault_input.lower() in ['quit', 'exit']:
                print(f"\n{YELLOW}🚫 Exiting the script.{RESET}")
                print("")
                sys.exit(0)

            # Display the list of vaults if the user presses Enter or types 'list'.
            if not vault_input or vault_input.lower() == 'list':
                vaults_json = run_op_command(["vault", "list", "--format=json"])
                if vaults_json:
                    vaults = json.loads(vaults_json)
                    print(f"\n{CYAN}📋 Available vaults:{RESET}")
                    for v in vaults:
                        print(f"  - {v['name']} (ID: {v['id']})")
                show_list_prompt = False
                continue

            # Check if the input matches a vault name or UUID.
            vaults_json = run_op_command(["vault", "list", "--format=json"])
            if vaults_json:
                vaults = json.loads(vaults_json)
                vault = next((v for v in vaults if v['name'] == vault_input or v['id'] == vault_input), None)
                if not vault:
                    print(f"\n{RED}😕 Couldn't find a vault with name or UUID '{vault_input}'. Try again or press Enter to list all vaults!{RESET}")
                    show_list_prompt = False
    else:
        print(f"\n{RED}😕 Please enter 'y', 'n', or press Enter for 'y'!{RESET}")

# Prompt for and update the website URL until confirmed.
confirmed = False
while not confirmed:
    # Get the new URL.
    new_url = ""
    while not new_url:
        print("")
        print("🌐 What's the new website URL you want to set? (e.g., https://example.com)")
        new_url = input(f"{YELLOW}➡️ Enter the URL: {RESET}").strip()
        if not new_url:
            print(f"\n{RED}😕 Please provide a URL to continue!{RESET}")

    # Confirm the entered URL.
    url_confirmed = False
    while not url_confirmed:
        print("")
        print(f"You entered '{new_url}'. Is that right? (y/n, Enter for y)")
        confirm_url = input(f"{YELLOW}➡️ Enter your choice: {RESET}").strip()
        if not confirm_url:
            confirm_url = 'y'
        if confirm_url.lower() == 'y':
            url_confirmed = True
        elif confirm_url.lower() == 'n':
            new_url = ""
            while not new_url:
                print("")
                print("🌐 What's the new website URL you want to set? (e.g., https://example.com)")
                new_url = input(f"{YELLOW}➡️ Enter the URL: {RESET}").strip()
                if not new_url:
                    print(f"\n{RED}😕 Please provide a URL to continue!{RESET}")
        else:
            print(f"\n{RED}😕 Please enter 'y', 'n', or press Enter for 'y'!{RESET}")

    # Retrieve items from the selected vault.
    items_json = run_op_command(["item", "list", "--vault", vault["id"], "--format=json"])
    if not items_json:
        print(f"\n{YELLOW}😕 No items found in vault '{vault['name']}'. Nothing to update!{RESET}")
        print("")
        sys.exit(0)
    items = json.loads(items_json)

    # Initialize a thread-safe list for tracking changes.
    changes = []
    changes_lock = threading.Lock()

    # Update each item’s website field using multi-threading (3 threads).
    def update_item(item: Dict[str, str], new_url: str, changes: List[Dict[str, str]], lock: threading.Lock) -> None:
        # Retrieve item details in plain text.
        item_details = run_op_command(["item", "get", item["id"]])
        if not item_details:
            return

        # Parse the URLs section to extract the primary URL.
        current_website = ""
        in_urls_section = False
        for line in item_details.split("\n"):
            if line.startswith("URLs:"):
                in_urls_section = True
                continue
            if in_urls_section and "(primary)" in line:
                current_website = line.split("(primary)")[0].replace(":", "").strip()
                break
            if in_urls_section and not line.startswith(":"):
                break

        # Update the item’s website field.
        run_op_command(["item", "edit", item["id"], f"website={new_url}"])

        # Add the change to the thread-safe list.
        change = {
            "ItemID": item["id"],
            "ItemTitle": item["title"],
            "OldWebsite": current_website,
            "NewWebsite": new_url
        }
        with lock:
            changes.append(change)

    print("")
    print(f"{CYAN}🔧 Updating website fields for {len(items)} items...{RESET}")

    # Execute updates in parallel with 3 threads.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(update_item, item, new_url, changes, changes_lock) for item in items]

        # Display progress bar and spinner.
        spinner = itertools.cycle(['|', '/', '-', '\\'])
        with tqdm(total=len(items), desc="Processing items", unit="item") as pbar:
            completed_items = 0
            while completed_items < len(items):
                completed_items = len(changes)
                pbar.n = completed_items
                pbar.refresh()
                sys.stdout.write(f"\r{CYAN}Processing items ({completed_items} of {len(items)}) {next(spinner)}{RESET}")
                sys.stdout.flush()
                time.sleep(0.1)
            pbar.n = len(items)
            pbar.refresh()

    # Clear the spinner line.
    sys.stdout.write(f"\r{' ' * 50}\r")
    sys.stdout.flush()

    # Save changes to a CSV file.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"website_changes_{vault['name']}_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ItemID", "ItemTitle", "OldWebsite", "NewWebsite"])
        writer.writeheader()
        writer.writerows(changes)
    full_csv_path = os.path.abspath(csv_path)

    # Display changes and confirm with the user.
    changes_confirmed = False
    while not changes_confirmed:
        print("")
        print(f"{CYAN}📊 Update complete!{RESET}")
        if not changes:
            print(f"{YELLOW}😕 No items were updated in the vault.{RESET}")
        else:
            show_table_in_box(changes)
            print("")
            print(f"{CYAN}Here’s what we changed (saved to {full_csv_path}):{RESET}")
            print("")
        print("Review the output or CSV. Happy with the changes? (y/n/revert, Enter for y)")
        print("")
        confirm_changes = input(f"{YELLOW}➡️ Enter your choice: {RESET}").strip()

        # Default to 'y' if Enter is pressed.
        if not confirm_changes:
            confirm_changes = 'y'

        if confirm_changes.lower() == 'revert':
            print("")
            print(f"{YELLOW}🔄 Reverting changes...{RESET}")
            completed_items = 0

            # Revert changes using multi-threading (3 threads).
            def revert_item(change: Dict[str, str]) -> None:
                if change["OldWebsite"]:
                    run_op_command(["item", "edit", change["ItemID"], f"website={change['OldWebsite']}"])
                else:
                    run_op_command(["item", "edit", change["ItemID"], "website="])

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(revert_item, change) for change in changes]
                with tqdm(total=len(changes), desc="Reverting items", unit="item") as pbar:
                    while completed_items < len(changes):
                        completed_items = len(changes)
                        pbar.n = completed_items
                        pbar.refresh()
                        sys.stdout.write(f"\r{CYAN}Reverting items ({completed_items} of {len(changes)}) {next(spinner)}{RESET}")
                        sys.stdout.flush()
                        time.sleep(0.1)
                    pbar.n = len(changes)
                    pbar.refresh()

            # Clear the spinner line.
            sys.stdout.write(f"\r{' ' * 50}\r")
            sys.stdout.flush()
            print(f"\n{CYAN}🎉 Changes reverted successfully!{RESET}")
            print("")
            sys.exit(0)
        elif confirm_changes.lower() == 'y':
            changes_confirmed = True
            confirmed = True
        elif confirm_changes.lower() == 'n':
            print("")
            print(f"{YELLOW}😕 Not satisfied? Let's try a different URL!{RESET}")
            break
        else:
            print(f"\n{RED}😕 Please enter 'y', 'n', 'revert', or press Enter for 'y'!{RESET}")

# Confirm successful completion.
print("")
print(f"{CYAN}🎈 Website fields updated successfully. CSV saved at {full_csv_path}.{RESET}")
print("")