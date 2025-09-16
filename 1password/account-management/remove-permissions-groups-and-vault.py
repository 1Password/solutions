import subprocess
import csv
import threading
import sys
import os
import queue
import time
import json
from datetime import datetime
from typing import List, Tuple, Dict
from tqdm import tqdm

# Colors for console output
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"

# Valid permissions for 1Password Teams and Business
VALID_PERMISSIONS = {
    "allow_viewing", "allow_editing", "allow_managing",
    "view_items", "view_and_copy_passwords", "view_item_history",
    "create_items", "edit_items", "archive_items", "delete_items",
    "import_items", "export_items", "copy_and_share_items", "print_items",
    "manage_vault"
}

# Permission mappings for automatic removals and prompts
PERMISSION_MAPPINGS = {
    "allow_editing": {
        "additional_perms": ["archive_items", "delete_items", "copy_and_share_items"],
        "requires_prompt": False,
        "requires_confirmation": True,
        "warning_message": None
    },
    "allow_managing": {
        "additional_perms": ["manage_vault"],
        "requires_prompt": False,
        "requires_confirmation": True,
        "warning_message": None
    },
    "allow_viewing": {
        "additional_perms": ["view_items", "view_and_copy_passwords", "view_item_history", "create_items", "edit_items", "archive_items", "delete_items", "import_items", "export_items", "copy_and_share_items", "print_items"],
        "requires_prompt": True,
        "requires_confirmation": True,
        "prompt_depends": ["allow_editing"],
        "warning_message": "All permissions except manage_vault"
    },
    "archive_items": {
        "additional_perms": [],
        "requires_prompt": False,
        "requires_confirmation": False,
        "warning_message": None
    },
    "copy_and_share_items": {
        "additional_perms": [],
        "requires_prompt": False,
        "requires_confirmation": True,
        "warning_message": None
    },
    "create_items": {
        "additional_perms": ["import_items"],
        "requires_prompt": True,
        "requires_confirmation": True,
        "prompt_depends": ["import_items"],
        "warning_message": None
    },
    "delete_items": {
        "additional_perms": ["copy_and_share_items"],
        "requires_prompt": False,
        "requires_confirmation": True,
        "warning_message": None
    },
    "edit_items": {
        "additional_perms": ["archive_items", "delete_items", "copy_and_share_items"],
        "requires_prompt": True,
        "requires_confirmation": True,
        "prompt_depends": ["archive_items", "delete_items"],
        "warning_message": None
    },
    "export_items": {
        "additional_perms": [],
        "requires_prompt": False,
        "requires_confirmation": False,
        "warning_message": None
    },
    "import_items": {
        "additional_perms": [],
        "requires_prompt": False,
        "requires_confirmation": False,
        "warning_message": None
    },
    "manage_vault": {
        "additional_perms": [],
        "requires_prompt": False,
        "requires_confirmation": False,
        "warning_message": None
    },
    "print_items": {
        "additional_perms": [],
        "requires_prompt": False,
        "requires_confirmation": False,
        "warning_message": None
    },
    "view_and_copy_passwords": {
        "additional_perms": ["edit_items", "archive_items", "delete_items", "view_item_history", "export_items", "copy_and_share_items"],
        "requires_prompt": True,
        "requires_confirmation": True,
        "prompt_depends": ["edit_items", "archive_items", "delete_items", "view_item_history", "export_items", "copy_and_share_items"],
        "warning_message": None
    },
    "view_item_history": {
        "additional_perms": ["export_items", "copy_and_share_items", "print_items"],
        "requires_prompt": True,
        "requires_confirmation": True,
        "prompt_depends": ["export_items", "copy_and_share_items", "print_items"],
        "warning_message": None
    },
    "view_items": {
        "additional_perms": ["create_items", "edit_items", "archive_items", "delete_items", "view_and_copy_passwords", "view_item_history", "import_items", "export_items", "copy_and_share_items", "print_items"],
        "requires_prompt": True,
        "requires_confirmation": True,
        "prompt_depends": ["create_items", "edit_items", "archive_items", "delete_items", "view_and_copy_passwords", "view_item_history", "import_items", "export_items", "copy_and_share_items", "print_items"],
        "warning_message": "All permissions except manage_vault"
    }
}

# Queue for handling vault processing tasks
process_queue = queue.Queue()
process_thread_running = threading.Event()
results_lock = threading.Lock()

def process_vaults(permissions: List[str], vault_names: Dict[str, Dict[str, str]], group_names: Dict[str, str], csv_writer: csv.DictWriter, failure_count: List[int]) -> None:
    # Process vault-group pairs: revoke permissions, update failure count
    semaphore = threading.Semaphore(7)
    while process_thread_running.is_set():
        try:
            vault_id, group_id, lock = process_queue.get_nowait()
            with semaphore:
                # Handle each permission
                revoke_perms = []
                additional_perms = []
                requires_prompt = False
                prompt_depends = []

                # Build revoke permissions based on mappings
                for perm in permissions:
                    if perm in PERMISSION_MAPPINGS:
                        mapping = PERMISSION_MAPPINGS[perm]
                        revoke_perms.append(perm)
                        revoke_perms.extend(mapping["additional_perms"])
                        additional_perms.append(perm)
                        additional_perms.extend(mapping["additional_perms"])
                        if mapping["requires_prompt"]:
                            requires_prompt = True
                            prompt_depends.extend(mapping.get("prompt_depends", []))
                        revoke_perms.extend(prompt_depends)
                    else:
                        revoke_perms.append(perm)
                        additional_perms.append(perm)

                        # Remove duplicates while preserving order
                        revoke_perms = list(dict.fromkeys(revoke_perms))
                        additional_perms = list(dict.fromkeys(additional_perms))

                # Check if revoke_perms is empty
                if not revoke_perms:
                    status = "Skipped"
                    error_msg = "No valid permissions to revoke"
                    with lock:
                        csv_writer.writerow({
                            "Timestamp": datetime.now().isoformat(),
                            "Vault_ID": vault_id,
                            "Vault_Name": vault_names.get(group_id, {}).get(vault_id, vault_id),
                            "Group_ID": group_id,
                            "Group_Name": group_names.get(group_id, group_id),
                            "Status": status,
                            "Error": error_msg
                        })
                    process_queue.task_done()
                    continue

                # Execute the revoke command
                cmd = ["vault", "group", "revoke", "--vault", vault_id, "--group", group_id, "--permissions", ",".join(revoke_perms)]
                status = "Success"
                error_msg = ""

                if requires_prompt:
                    # Use subprocess.Popen for interactive prompt
                    process = subprocess.Popen(
                        ["op"] + cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        env=dict(os.environ, PYTHONUNBUFFERED="1")
                    )
                    output = []
                    prompt_detected = False
                    prompt_perms = ""
                    start_time = time.time()
                    while process.poll() is None and time.time() - start_time < 10:
                        try:
                            line = process.stdout.readline().strip()
                            if line:
                                output.append(line)
                                if "In order to remove" in line and "[Y/n]" in line:
                                    prompt_detected = True
                                    start = line.find("the permission(s) [") + 18
                                    end = line.find("]", start)
                                    prompt_perms = line[start:end]
                                    process.stdin.write("Y\n")
                                    process.stdin.flush()
                                    break
                            line = process.stderr.readline().strip()
                            if line:
                                output.append(line)
                        except IOError:
                            time.sleep(0.1)
                    if not prompt_detected:
                        stdout, stderr = process.communicate(timeout=5)
                        output.extend(stdout.splitlines())
                        output.extend(stderr.splitlines())

                    return_code = process.poll() or process.returncode
                else:
                    # Non-interactive command
                    result = subprocess.run(
                        ["op"] + cmd,
                        capture_output=True,
                        text=True,
                        env=dict(os.environ, PYTHONUNBUFFERED="1")
                    )
                    output = (result.stdout + result.stderr).splitlines()
                    return_code = result.returncode

                if return_code == 0:
                    status = "Success"
                    if additional_perms:
                        if "view_items" in permissions or "allow_viewing" in permissions:
                            error_msg = "Removed all permissions except manage_vault"
                        else:
                            error_msg = f"Removed permissions: {','.join(additional_perms)}"
                else:
                    # Parse error for dependencies as a fallback
                    error_text = "\n".join(output)
                    if "dependent on the permission(s)" in error_text:
                        start = error_text.find("dependent on the permission(s)") + 30
                        end = error_text.find("\n", start) or len(error_text)
                        dep_perms = error_text[start:end].split(", ")
                        new_perms = list(dict.fromkeys(revoke_perms + [p for p in dep_perms if p in VALID_PERMISSIONS and p not in revoke_perms]))
                        cmd = ["vault", "group", "revoke", "--vault", vault_id, "--group", group_id, "--permissions", ",".join(new_perms)]

                        result = subprocess.run(
                            ["op"] + cmd,
                            capture_output=True,
                            text=True,
                            env=dict(os.environ, PYTHONUNBUFFERED="1")
                        )
                        output = (result.stdout + result.stderr).splitlines()

                        if result.returncode == 0:
                            status = "Success"
                            if "view_items" in permissions or "allow_viewing" in permissions:
                                error_msg = "Removed all permissions except manage_vault"
                            else:
                                error_msg = f"Removed permissions including dependencies: {','.join(new_perms)}"
                        else:
                            status = "Failed"
                            error_msg = "\n".join(output) or f"Unknown CLI error (command: {' '.join(['op'] + cmd)})"
                            with results_lock:
                                failure_count[0] += 1
                    else:
                        status = "Failed"
                        error_msg = "\n".join(output) or f"Unknown CLI error (command: {' '.join(['op'] + cmd)})"
                        with results_lock:
                            failure_count[0] += 1

                with lock:
                    csv_writer.writerow({
                        "Timestamp": datetime.now().isoformat(),
                        "Vault_ID": vault_id,
                        "Vault_Name": vault_names.get(group_id, {}).get(vault_id, vault_id),
                        "Group_ID": group_id,
                        "Group_Name": group_names.get(group_id, group_id),
                        "Status": status,
                        "Error": error_msg
                    })
                process_queue.task_done()
                time.sleep(0.3)
        except queue.Empty:
            time.sleep(0.1)
        except Exception as e:
            print(f"{RED}⚠️ Error processing vault {vault_id}, group {group_id}: {e}{RESET}")
            with results_lock:
                failure_count[0] += 1

def show_table(data: List[Dict[str, str]]) -> None:
    # Display a styled ASCII table for groups or vaults
    headers = ["ID" if "GroupID" in data[0] else "VaultID", "Name" if "GroupName" in data[0] else "VaultName"]
    max_lengths = {"ID": 26, "Name": 50}
    for key in max_lengths:
        max_lengths[key] = max(
            max(len(item.get(key.replace("ID", "GroupID").replace("Name", "GroupName"), "")[:max_lengths[key]]) for item in data),
            len(key)
        ) + 2

    top_border = f"┌{'─' * max_lengths['ID']}┬{'─' * max_lengths['Name']}┐"
    header_row = f"│ {headers[0].ljust(max_lengths['ID'] - 2)} │ {headers[1].ljust(max_lengths['Name'] - 2)} │"
    mid_border = f"├{'─' * max_lengths['ID']}┼{'─' * max_lengths['Name']}┤"
    bottom_border = f"└{'─' * max_lengths['ID']}┴{'─' * max_lengths['Name']}┘"

    print(f"{CYAN}{top_border}{RESET}")
    print(f"{CYAN}{header_row}{RESET}")
    print(f"{CYAN}{mid_border}{RESET}")
    for item in data:
        id_field = item.get("GroupID" if "GroupID" in data[0] else "VaultID", "")[:max_lengths['ID']-2].ljust(max_lengths['ID']-2)
        name_field = item.get("GroupName" if "GroupName" in data[0] else "VaultName", "")[:max_lengths['Name']-2].ljust(max_lengths['Name']-2)
        print(f"│ {id_field} │ {name_field} │")
    print(f"{CYAN}{bottom_border}{RESET}")

def run_op_command(args: List[str]) -> Tuple[str, str]:
    # Run a 1Password CLI command and return stdout, stderr
    cmd = ["op"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout, ""
    except subprocess.CalledProcessError as e:
        return "", e.stderr.strip() or f"Unknown CLI error (command: {' '.join(cmd)})"
    except FileNotFoundError:
        return "", "1Password CLI ('op') not found. Please ensure it is installed."

def check_op_auth() -> bool:
    # Check if authenticated with 1Password CLI; sign in if needed
    stdout, stderr = run_op_command(["user", "list"])
    if stdout:
        print(f"{GREEN}✅ Authenticated with 1Password CLI{RESET}\n")
        return True
    print(f"{YELLOW}Please authenticate with 1Password CLI{RESET}")
    account = input(f"{YELLOW}> Account shorthand (e.g., 'myaccount'): {RESET}").strip()
    print()
    if not account:
        print(f"{RED}⚠️ Account shorthand required{RESET}\n")
        return False
    stdout, stderr = run_op_command(["signin", "--account", account, "--raw"])
    if stdout:
        os.environ[f"OP_SESSION_{account}"] = stdout.strip()
        print(f"{GREEN}✅ Signed in successfully{RESET}\n")
        return True
    print(f"{RED}⚠️ Sign-in failed: {stderr}{RESET}\n")
    return False

def get_vaults_for_group(group_id: str, group_name: str) -> List[Tuple[str, str]]:
    # Get vaults a group has access to using op vault list --group
    cmd = ["vault", "list", "--group", group_id]
    stdout, stderr = run_op_command(cmd)
    if stdout:
        vaults = []
        for line in stdout.strip().splitlines()[1:]:
            parts = line.split(maxsplit=1)
            if len(parts) >= 2:
                vaults.append((parts[0], parts[1]))
        if not vaults:
            print(f"{YELLOW}⚠️ No vaults found for group {group_name} ({group_id}){RESET}")
        return vaults
    print(f"{RED}⚠️ Failed to list vaults for group {group_name} ({group_id}): {stderr}{RESET}")
    return []

def get_groups() -> List[Tuple[str, str]]:
    # Get all groups using op group list, excluding Recovery
    stdout, stderr = run_op_command(["group", "list"])
    if stdout:
        groups = []
        for line in stdout.strip().splitlines()[1:]:
            parts = line.split(maxsplit=1)
            if len(parts) >= 2 and parts[1] != "Recovery":
                groups.append((parts[0], parts[1]))
        return groups
    print(f"{RED}⚠️ Failed to list groups: {stderr}{RESET}")
    return []

def get_groups_selection() -> List[Tuple[str, str]]:
    # Prompt user for multiple groups, disambiguating if needed
    while True:
        print("\nEnter group IDs/names (comma-separated, Enter to list):")
        group_input = input(f"{YELLOW}> {RESET}").strip()
        
        if not group_input:
            print(f"\n{CYAN}Available groups:{RESET}")
            groups = get_groups()
            if not groups:
                print(f"{YELLOW}⚠️ No groups found{RESET}")
                sys.exit(1)
            show_table([{"GroupID": gid, "GroupName": gname} for gid, gname in sorted(groups, key=lambda x: x[1])])
            continue
        
        group_inputs = [g.strip() for g in group_input.split(",")]
        selected_groups = []
        groups = get_groups()
        invalid_groups = []

        for g_input in group_inputs:
            matches = [(gid, gname) for gid, gname in groups if g_input == gid or g_input.lower() in gname.lower()]
            if len(matches) == 1:
                selected_groups.append(matches[0])
            elif len(matches) > 1:
                print(f"\n{CYAN}Multiple groups match '{g_input}':{RESET}")
                show_table([{"GroupID": gid, "GroupName": gname} for gid, gname in matches])
                while True:
                    uuid_input = input(f"{YELLOW}> Enter the UUID of the correct group for '{g_input}': {RESET}").strip()
                    for gid, gname in matches:
                        if uuid_input == gid:
                            selected_groups.append((gid, gname))
                            break
                    else:
                        print(f"{YELLOW}⚠️ Invalid UUID. Please select a UUID from the list.{RESET}")
                        continue
                    break
            else:
                invalid_groups.append(g_input)

        if invalid_groups:
            print(f"{YELLOW}⚠️ Invalid groups: {', '.join(invalid_groups)}{RESET}")
            continue
        if not selected_groups:
            print(f"{RED}⚠️ At least one valid group required{RESET}")
            continue
        return selected_groups

def get_permissions() -> List[str]:
    # Prompt user for permissions to remove
    while True:
        print("\nEnter permissions to remove (comma-separated, Enter to list):")
        perm_input = input(f"{YELLOW}> {RESET}").strip()
        if not perm_input:
            print(f"\n{CYAN}Available permissions:{RESET}")
            for perm in sorted(VALID_PERMISSIONS):
                print(f"  - {perm}")
            continue
        
        permissions = [p.strip() for p in perm_input.split(",")]
        invalid = [p for p in permissions if p not in VALID_PERMISSIONS]
        if invalid:
            print(f"{YELLOW}⚠️ Invalid permissions: {', '.join(invalid)}{RESET}")
            continue
        if not permissions:
            print(f"{RED}⚠️ At least one permission required{RESET}")
            continue
        return permissions

def main() -> None:
    # Ensure we're authenticated before starting
    if not check_op_auth():
        sys.exit(1)

    print(f"{CYAN}🚀 Removing permissions...{RESET}\n")

    # Set up CSV output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"vault_permission_changes_{timestamp}.csv"
    csv_fields = ["Timestamp", "Vault_ID", "Vault_Name", "Group_ID", "Group_Name", "Status", "Error"]
    lock = threading.Lock()

    with open(csv_file, "w", newline="") as f:
        csv_writer = csv.DictWriter(f, fieldnames=csv_fields)
        csv_writer.writeheader()

        # Let user pick multiple groups
        selected_groups = get_groups_selection()
        print(f"\n{CYAN}Groups: {', '.join(g[1] for g in selected_groups)}{RESET}")

        # Get vaults for all groups with feedback
        print(f"{CYAN}Gathering vault information...{RESET}", end="\r")
        vault_names = {}  # Map group_id to {vault_id: vault_name}
        group_names = {g[0]: g[1] for g in selected_groups}
        all_vaults = set()
        group_vault_pairs = []
        errors = []
        for group_id, group_name in selected_groups:
            vaults = get_vaults_for_group(group_id, group_name)
            if not vaults:
                _, stderr = run_op_command(["vault", "list", "--group", group_id])
                if stderr:
                    errors.append(f"Failed to list vaults for group {group_name} ({group_id}): {stderr}")
            vault_names[group_id] = {v[0]: v[1] for v in vaults}
            for vault_id, _ in vaults:
                if (vault_id, group_id) not in all_vaults:
                    group_vault_pairs.append((vault_id, group_id))
                    all_vaults.add((vault_id, group_id))
        sys.stdout.write("\r" + " " * 50 + "\r")
        sys.stdout.flush()

        if not group_vault_pairs:
            print(f"{RED}⚠️ No vaults found for selected groups. Exiting.{RESET}")
            if errors:
                print(f"{RED}Errors encountered:{RESET}")
                for error in errors:
                    print(f"  - {error}")
            sys.exit(1)

        # Ask to process all vaults or specific ones
        print(f"\nProcess all {len(group_vault_pairs)} vault-group pairs? (Y/n, Enter for Yes):")
        choice = input(f"{YELLOW}> {RESET}").strip().lower()
        
        selected_pairs = []
        if choice in ("", "y", "yes"):
            selected_pairs = group_vault_pairs
        else:
            print(f"\nEnter vault names/UUIDs (comma-separated, Enter to list):")
            available_vaults = [(v[0], v[1], vault_names[v[1]].get(v[0], v[0]), group_names[v[1]]) for v in group_vault_pairs]
            while True:
                vault_input = input(f"{YELLOW}> {RESET}").strip()
                if not vault_input:
                    print(f"\n{CYAN}Available vaults:{RESET}")
                    for vault_id, group_id, vault_name, group_name in available_vaults:
                        print(f"  - {vault_name} (ID: {vault_id}, Group: {group_name})")
                    print(f"\nEnter vault names/UUIDs (comma-separated):")
                    continue
                vault_inputs = [v.strip() for v in vault_input.split(",")]
                invalid_vaults = []
                for v_input in vault_inputs:
                    found = False
                    for vault_id, group_id, vault_name, group_name in available_vaults:
                        if v_input in (vault_id, vault_name):
                            if (vault_id, group_id) not in selected_pairs:
                                selected_pairs.append((vault_id, group_id))
                                print(f"{CYAN}Vault selected: {vault_name} (Group: {group_name}){RESET}")
                            found = True
                            break
                    if not found:
                        invalid_vaults.append(v_input)
                
                if invalid_vaults:
                    print(f"{YELLOW}⚠️ Invalid vaults: {', '.join(invalid_vaults)}{RESET}")
                
                print(f"\nAdd more vaults? (Y/n, Enter for No):")
                if input(f"{YELLOW}> {RESET}").strip().lower() not in ("y", "yes"):
                    break

        if not selected_pairs:
            print(f"{RED}⚠️ No vault-group pairs selected. Exiting.{RESET}")
            sys.exit(1)

        # Get permissions to remove
        permissions = get_permissions()
        print(f"\n{CYAN}Permissions: {', '.join(permissions)}{RESET}")

        # Confirm permissions with additional removals
        confirmed_permissions = []
        requires_overall_confirmation = True
        for perm in permissions:
            add_perms = []
            if perm in PERMISSION_MAPPINGS and PERMISSION_MAPPINGS[perm]["requires_confirmation"]:
                mapping = PERMISSION_MAPPINGS[perm]
                if mapping.get("warning_message"):
                    add_perms = [mapping["warning_message"]]
                else:
                    add_perms = mapping["additional_perms"]
                requires_overall_confirmation = False

            if add_perms:
                print(f"\n{RED}⚠️ WARNING: Removing {perm} will also remove: {', '.join(add_perms)} ⚠️{RESET}")
                confirm = input(f"{YELLOW}> Confirm removing {perm} and additional permissions? [Y/n]: {RESET}").strip().lower()
                print()
                if confirm in ("", "y", "yes"):
                    confirmed_permissions.append(perm)
                else:
                    print(f"{YELLOW}⚠️ Skipped {perm}{RESET}")
                    # Log skipped permission
                    for vault_id, group_id in selected_pairs:
                        with lock:
                            csv_writer.writerow({
                                "Timestamp": datetime.now().isoformat(),
                                "Vault_ID": vault_id,
                                "Vault_Name": vault_names.get(group_id, {}).get(vault_id, vault_id),
                                "Group_ID": group_id,
                                "Group_Name": group_names.get(group_id, group_id),
                                "Status": "Skipped",
                                "Error": f"User declined to remove {perm} and additional permissions: {','.join(add_perms)}"
                            })
            else:
                confirmed_permissions.append(perm)

        if not confirmed_permissions:
            print(f"{RED}⚠️ No permissions confirmed for removal. Exiting.{RESET}")
            sys.exit(1)

        # Only show overall confirmation if no permissions required individual confirmation
        if requires_overall_confirmation:
            print(f"\nConfirm removing {', '.join(confirmed_permissions)} for {len(selected_groups)} group(s) across {len(selected_pairs)} pair(s)? (Y/n, Enter for Yes):")
            confirm = input(f"{YELLOW}> {RESET}").strip().lower()
            if confirm not in ("", "y", "yes"):
                print(f"{YELLOW}⚠️ Cancelled{RESET}")
                sys.exit(0)

        # Process vault-group pairs: check and revoke permissions
        print(f"\n{CYAN}Processing {len(selected_pairs)} vault-group pair(s)...{RESET}")
        failure_count = [0]  # Use a list to allow modification in thread
        process_thread_running.set()
        process_thread = threading.Thread(target=process_vaults, args=(confirmed_permissions, vault_names, group_names, csv_writer, failure_count))
        process_thread.daemon = True
        process_thread.start()

        for vault_id, group_id in selected_pairs:
            process_queue.put((vault_id, group_id, lock))

        with tqdm(total=len(selected_pairs), desc="Processing", unit="pair") as pbar:
            while not process_queue.empty():
                pbar.n = len(selected_pairs) - process_queue.qsize()
                pbar.refresh()
                time.sleep(0.1)
            pbar.n = len(selected_pairs)
            pbar.refresh()

        process_queue.join()
        process_thread_running.clear()
        process_thread.join()
        sys.stdout.write(f"\r{' ' * 50}\r")
        sys.stdout.flush()

        # All done!
        full_csv_path = os.path.abspath(csv_file)
        print(f"\n{GREEN}🎉 Done! Results saved to {full_csv_path}{RESET}")
        if failure_count[0] > 0:
            print(f"{YELLOW}⚠️ {failure_count[0]} vault-group pair(s) failed to process. See CSV for details.{RESET}")

if __name__ == "__main__":
    main()