import subprocess
import csv
import re
import os
import sys
import threading
import time
from datetime import datetime
from queue import Queue
from typing import List, Dict, Optional, Any, Tuple

# ANSI color codes for colorful terminal output
CYAN: str = "\033[96m"
YELLOW: str = "\033[93m"
RED: str = "\033[91m"
GREEN: str = "\033[92m"
RESET: str = "\033[0m"
BLINK: str = "\033[5m"

def wrap_text(text: str, max_width: int) -> List[str]:
    # Break text into lines that fit within a set width
    if not text:
        return [""]

    lines: List[str] = []
    current_line: str = ""
    words: List[str] = text.split()

    # Process each word, wrapping if it exceeds max width
    for word in words:
        if len(word) > max_width:
            # Handle words longer than max width by splitting them
            while len(word) > max_width:
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                lines.append(word[:max_width])
                word = word[max_width:]
            if word:
                current_line = f"{current_line} {word}" if current_line else word
        else:
            potential_line: str = f"{current_line} {word}" if current_line else word
            if len(potential_line) <= max_width:
                current_line = potential_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

    if current_line:
        lines.append(current_line)
    if not lines:
        lines = [""]
    return lines

def show_table(data: List[Dict[str, Any]], max_message_length: int = 30) -> None:
    # Print a neat table with Name, Email, Status, and Message
    if not data:
        print(f"\n{YELLOW}😕 No data to display.{RESET}")
        return

    headers: List[str] = ["Name", "Email", "Status", "Message"]
    max_lengths: Dict[str, int] = {h: len(h) for h in headers}
    max_lines: List[int] = []
    wrapped_data: List[Dict[str, Any]] = []

    # Calculate max width for each column and wrap messages
    for item in data:
        name: str = str(item.get("Name", ""))
        email: str = str(item.get("Email", ""))
        status: str = str(item.get("Status", ""))
        message: str = str(item.get("FullMessage", ""))

        wrapped_message: List[str] = wrap_text(message, max_message_length)
        message_lines: int = len(wrapped_message)

        max_lengths["Name"] = max(max_lengths["Name"], len(name))
        max_lengths["Email"] = max(max_lengths["Email"], len(email))
        max_lengths["Status"] = max(max_lengths["Status"], len(status))
        max_lengths["Message"] = max(max_lengths["Message"], max((len(line) for line in wrapped_message), default=0))

        max_lines.append(max(1, message_lines))
        wrapped_data.append({
            "Name": name,
            "Email": email,
            "Status": status,
            "Message": wrapped_message
        })

    # Set column widths with some padding, cap at reasonable limits
    for key in max_lengths:
        max_lengths[key] = max(max_lengths[key] + 4, 15)
        if key == "Email":
            max_lengths[key] = min(max_lengths[key], 60)
        else:
            max_lengths[key] = min(max_lengths[key], 40)

    # Build table borders and header row
    top_border: str = "┌" + "─" * max_lengths["Name"] + "┬" + "─" * max_lengths["Email"] + "┬" + "─" * max_lengths["Status"] + "┬" + "─" * max_lengths["Message"] + "┐"
    mid_border: str = "├" + "─" * max_lengths["Name"] + "┼" + "─" * max_lengths["Email"] + "┼" + "─" * max_lengths["Status"] + "┼" + "─" * max_lengths["Message"] + "┤"
    row_border: str = mid_border
    bottom_border: str = "└" + "─" * max_lengths["Name"] + "┴" + "─" * max_lengths["Email"] + "┴" + "─" * max_lengths["Status"] + "┴" + "─" * max_lengths["Message"] + "┘"
    header_row: str = f"│ {headers[0].ljust(max_lengths['Name'] - 2)} │ {headers[1].ljust(max_lengths['Email'] - 2)} │ {headers[2].ljust(max_lengths['Status'] - 2)} │ {headers[3].ljust(max_lengths['Message'] - 2)} │"

    print(f"\n{CYAN}{top_border}{RESET}")
    print(f"{CYAN}{header_row}{RESET}")
    print(f"{CYAN}{mid_border}{RESET}")

    # Print each row, handling multi-line messages
    for i, item in enumerate(wrapped_data):
        for j in range(max_lines[i]):
            name_text: str = item["Name"] if j == 0 else ""
            email_text: str = item["Email"] if j == 0 else ""
            status_text: str = item["Status"] if j == 0 else ""
            message_text: str = item["Message"][j] if j < len(item["Message"]) else ""

            row: str = f"│ {name_text.ljust(max_lengths['Name'] - 2)} │ {email_text.ljust(max_lengths['Email'] - 2)} │ {status_text.ljust(max_lengths['Status'] - 2)} │ {message_text.ljust(max_lengths['Message'] - 2)} │"
            print(row)
        if i < len(wrapped_data) - 1:
            print(f"{CYAN}{row_border}{RESET}")

    print(f"{CYAN}{bottom_border}{RESET}")

def show_email_list(emails: List[str], action: str, names: Optional[List[str]] = None) -> None:
    # Show a confirmation table of emails or users before an action
    if not emails:
        print(f"\n{YELLOW}😕 No users/emails to display.{RESET}")
        return

    headers: List[str] = ["Name", "UUID/Email"] if names else [f"Emails to {action}"]
    max_lengths: Dict[str, int] = {"Name": len(headers[0]), "Identifier": len(headers[1])} if names else {"Email": len(headers[0])}
    max_lines: List[int] = []
    wrapped_data: List[Dict[str, str]] = []

    # Prepare data with names and identifiers (or just emails)
    if names:
        for i, email in enumerate(emails):
            name: str = names[i] if i < len(names) else ""
            max_lengths["Name"] = max(max_lengths["Name"], len(name))
            max_lengths["Identifier"] = max(max_lengths["Identifier"], len(email))
            max_lines.append(1)
            wrapped_data.append({"Name": name, "Identifier": email})

        max_lengths["Name"] = max(max_lengths["Name"] + 4, 15)
        max_lengths["Identifier"] = max(max_lengths["Identifier"] + 4, 15)

        # Build table structure with two columns
        top_border: str = "┌" + "─" * max_lengths["Name"] + "┬" + "─" * max_lengths["Identifier"] + "┐"
        mid_border: str = "├" + "─" * max_lengths["Name"] + "┼" + "─" * max_lengths["Identifier"] + "┤"
        row_border: str = mid_border
        bottom_border: str = "└" + "─" * max_lengths["Name"] + "┴" + "─" * max_lengths["Identifier"] + "┘"
        header_row: str = f"│ {headers[0].ljust(max_lengths['Name'] - 2)} │ {headers[1].ljust(max_lengths['Identifier'] - 2)} │"

        print(f"\n{YELLOW}{top_border}{RESET}")
        print(f"{YELLOW}{header_row}{RESET}")
        print(f"{YELLOW}{mid_border}{RESET}")

        for i, item in enumerate(wrapped_data):
            row: str = f"│ {item['Name'].ljust(max_lengths['Name'] - 2)} │ {item['Identifier'].ljust(max_lengths['Identifier'] - 2)} │"
            print(f"{YELLOW}{row}{RESET}")
            if i < len(wrapped_data) - 1:
                print(f"{YELLOW}{row_border}{RESET}")

        print(f"{YELLOW}{bottom_border}{RESET}")
    else:
        for email in emails:
            max_lengths["Email"] = max(max_lengths["Email"], len(email))
            max_lines.append(1)
            wrapped_data.append({"Email": email})

        max_lengths["Email"] = max(max_lengths["Email"] + 4, 15)
        top_border: str = "┌" + "─" * max_lengths["Email"] + "┐"
        mid_border: str = "├" + "─" * max_lengths["Email"] + "┤"
        row_border: str = mid_border
        bottom_border: str = "└" + "─" * max_lengths["Email"] + "┘"
        header_row: str = f"│ {headers[0].ljust(max_lengths['Email'] - 2)} │"

        print(f"\n{YELLOW}{top_border}{RESET}")
        print(f"{YELLOW}{header_row}{RESET}")
        print(f"{YELLOW}{mid_border}{RESET}")

        for i, item in enumerate(wrapped_data):
            row: str = f"│ {item['Email'].ljust(max_lengths['Email'] - 2)} │"
            print(f"{YELLOW}{row}{RESET}")
            if i < len(wrapped_data) - 1:
                print(f"{YELLOW}{row_border}{RESET}")

        print(f"{YELLOW}{bottom_border}{RESET}")

def show_user_list(action: str) -> Optional[List[Dict[str, str]]]:
    # Display a table of users (UUID, Name, Email, State) filtered by action
    op_result: Tuple[bool, str] = invoke_op_command(["user", "list"])
    if not op_result[0]:
        print(f"\n{RED}😕 Failed to retrieve user list: {op_result[1]}{RESET}")
        return None

    user_list_raw: str = op_result[1]
    if not user_list_raw:
        print(f"\n{YELLOW}😕 No users found.{RESET}")
        return None

    user_list_lines: List[str] = [line for line in user_list_raw.split("\n") if line.strip()]
    if len(user_list_lines) < 2:
        print(f"\n{YELLOW}😕 No users found in the list.{RESET}")
        return None

    user_data: List[Dict[str, str]] = []
    # Parse each line of 1Password CLI output
    for line in user_list_lines[1:]:
        line = line.strip()
        if not line or len(line) < 26:
            continue

        uuid: str = line[:26].strip()
        remaining: str = line[26:].strip()
        # Extract user state using regex
        state_match = re.search(r'\s+(SUSPENDED|TRANSFER_SUSPENDED|ACTIVE|PENDING|RECOVERY_STARTED|TRANSFER_STARTED)\s+', remaining)
        if not state_match:
            continue

        state: str = state_match.group(1)
        state_start: int = state_match.start()
        state_length: int = len(state_match.group(0))
        before_state: str = remaining[:state_start].strip()
        after_state: str = remaining[state_start + state_length:].strip()
        # Find email in the text before state
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', before_state)
        if not email_match:
            continue

        email: str = email_match.group(0)
        email_start: int = email_match.start()
        name: str = before_state[:email_start].strip() or "Unknown"

        # Filter users based on action (e.g., only active users for suspend)
        include_user: bool = False
        if action == "suspend":
            include_user = state in ["ACTIVE", "PENDING", "RECOVERY_STARTED", "TRANSFER_STARTED"]
        elif action == "reactivate":
            include_user = state in ["SUSPENDED", "TRANSFER_SUSPENDED"]
        else:
            include_user = True

        if include_user:
            user_data.append({
                "UUID": uuid,
                "Name": name,
                "Email": email,
                "State": state
            })

    if not user_data:
        print(f"\n{YELLOW}😕 No users found matching the criteria for {action}.{RESET}")
        return None

    headers: List[str] = ["UUID", "Name", "Email", "State"]
    max_lengths: Dict[str, int] = {h: len(h) for h in headers}
    max_lines: List[int] = []
    wrapped_data: List[Dict[str, str]] = []

    # Calculate column widths
    for user in user_data:
        max_lengths["UUID"] = max(max_lengths["UUID"], len(user["UUID"]))
        max_lengths["Name"] = max(max_lengths["Name"], len(user["Name"]))
        max_lengths["Email"] = max(max_lengths["Email"], len(user["Email"]))
        max_lengths["State"] = max(max_lengths["State"], len(user["State"]))
        max_lines.append(1)
        wrapped_data.append(user)

    for key in max_lengths:
        max_lengths[key] = max(max_lengths[key] + 4, 15)

    # Construct table borders and header
    top_border: str = "┌" + "─" * max_lengths["UUID"] + "┬" + "─" * max_lengths["Name"] + "┬" + "─" * max_lengths["Email"] + "┬" + "─" * max_lengths["State"] + "┐"
    mid_border: str = "├" + "─" * max_lengths["UUID"] + "┼" + "─" * max_lengths["Name"] + "┼" + "─" * max_lengths["Email"] + "┼" + "─" * max_lengths["State"] + "┤"
    row_border: str = mid_border
    bottom_border: str = "└" + "─" * max_lengths["UUID"] + "┴" + "─" * max_lengths["Name"] + "┴" + "─" * max_lengths["Email"] + "┴" + "─" * max_lengths["State"] + "┘"
    header_row: str = f"│ {headers[0].ljust(max_lengths['UUID'] - 2)} │ {headers[1].ljust(max_lengths['Name'] - 2)} │ {headers[2].ljust(max_lengths['Email'] - 2)} │ {headers[3].ljust(max_lengths['State'] - 2)} │"

    print(f"\n{CYAN}{top_border}{RESET}")
    print(f"{CYAN}{header_row}{RESET}")
    print(f"{CYAN}{mid_border}{RESET}")

    # Print each user row
    for i, user in enumerate(wrapped_data):
        row: str = f"│ {user['UUID'].ljust(max_lengths['UUID'] - 2)} │ {user['Name'].ljust(max_lengths['Name'] - 2)} │ {user['Email'].ljust(max_lengths['Email'] - 2)} │ {user['State'].ljust(max_lengths['State'] - 2)} │"
        print(row)
        if i < len(wrapped_data) - 1:
            print(f"{CYAN}{row_border}{RESET}")

    print(f"{CYAN}{bottom_border}{RESET}")
    return user_data

def invoke_op_command(arguments: List[str]) -> Tuple[bool, str]:
    # Run a 1Password CLI command and handle its output
    try:
        # Execute the command and capture output
        process = subprocess.run(
            ["op"] + arguments,
            capture_output=True,
            text=True,
            check=False
        )
        stdout: str = process.stdout
        stderr: str = process.stderr
        exit_code: int = process.returncode

        # Check for errors in exit code or stderr
        if exit_code != 0 or (stderr and "[ERROR]" in stderr):
            return False, stderr

        # Map action to success message or use stdout
        result_message: str = {
            "provision": "Provisioned successfully",
            "suspend": "Suspended successfully",
            "reactivate": "Reactivated successfully",
            "delete": "Deleted successfully"
        }.get(arguments[1], stdout)

        return True, result_message
    except subprocess.SubprocessError as e:
        error_message: str = str(e)
        # Handle specific 1Password CLI errors
        if "TRANSFER_PENDING" in error_message or "TRANSFER_STARTED" in error_message:
            if arguments[1] == "provision":
                return True, "Provisioned successfully (transfer in progress)"
            return False, "User transfer in progress"
        elif "already a member" in error_message:
            return False, "User already exists"
        elif "not found" in error_message:
            return False, "User not found"
        elif "Resource Invalid" in error_message:
            return False, "Invalid domain"
        elif "expected at most 0 arguments" in error_message:
            return False, "Invalid command syntax"
        return False, error_message

def process_user(name: str, identifier: str, action: str, result_queue: Queue) -> None:
    # Process a single user for the given action (provision, suspend, etc.)
    status: str = "Success"
    message: str = ""
    full_message: str = ""

    # Validate identifier
    if not identifier:
        status = "Failed"
        message = "Missing email address" if action == "provision" else "Missing UUID or email address"
        full_message = message
    else:
        # Set up 1Password CLI command arguments
        op_args: List[str] = {
            "provision": ["user", "provision", "--name", name, "--email", identifier],
            "suspend": ["user", "suspend", identifier, "--deauthorize-devices-after", "5m"],
            "reactivate": ["user", "reactivate", identifier],
            "delete": ["user", "delete", identifier]
        }[action]
        message = {
            "provision": "Provisioned successfully",
            "suspend": "Suspended successfully",
            "reactivate": "Reactivated successfully",
            "delete": "Deleted successfully"
        }[action]
        # Run the command and check result
        op_result: Tuple[bool, str] = invoke_op_command(op_args)
        if not op_result[0]:
            status = "Failed"
            message = op_result[1]
            full_message = message
        else:
            status = "Success"
            message = op_result[1]
            full_message = message

    # Store result in queue for main thread
    result_queue.put({
        "Name": name,
        "Email": identifier,
        "Status": status,
        "FullMessage": full_message
    })

def main() -> None:
    # Manage 1Password users via CSV or manual input
    print(f"\n{CYAN}🚀 Welcome to the 1Password User Management Script! 🎉{RESET}")
    print("This script provisions, suspends, reactivates, or deletes users from a CSV file or manually.")
    print("CSV must have 'Name' and 'Email' columns (case-insensitive) if used.\n")

    # Check if 1Password CLI is installed
    try:
        subprocess.run(["op", "--version"], capture_output=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        print(f"{RED}😕 Error: 1Password CLI (op) not found. Please install it.{RESET}")
        print("Download from: https://developer.1password.com/docs/cli/get-started/\n")
        sys.exit(1)

    # Verify 1Password CLI authentication
    auth_check: Tuple[bool, str] = invoke_op_command(["user", "list"])
    if not auth_check[0]:
        print(f"{YELLOW}🔐 Looks like we need to authenticate with 1Password CLI.{RESET}")
        account_shorthand: str = input(f"{YELLOW}➡️ Account shorthand (e.g., 'myaccount' for 'myaccount.1password.com'): {RESET}")
        print()
        if not account_shorthand:
            print(f"{RED}😕 Account shorthand cannot be empty. Exiting.{RESET}\n")
            sys.exit(1)

        try:
            process = subprocess.run(
                ["op", "signin", "--account", account_shorthand, "--raw"],
                capture_output=True,
                text=True,
                check=True
            )
            session_token: str = process.stdout.strip()
            os.environ[f"OP_SESSION_{account_shorthand}"] = session_token
            print(f"{GREEN}✅ Successfully authenticated with 1Password CLI.{RESET}\n")
        except subprocess.SubprocessError as e:
            print(f"{RED}😕 Failed to authenticate with 1Password CLI: {str(e)}{RESET}\n")
            sys.exit(1)
    else:
        print(f"{GREEN}✅ Already authenticated with 1Password CLI.{RESET}\n")

    # Get input method (CSV, manual, export, or quit)
    input_method: Optional[str] = None
    valid_methods: List[str] = ["csv", "manual", "export", "quit"]
    first_prompt: bool = True

    while not input_method:
        print(f"\n{YELLOW}📋 How would you like to manage users?{RESET}")
        if first_prompt:
            print("  1. Use a CSV file\n  2. Manually enter user details\n  3. Actually I want to export a csv list\n  4. Quit\n")
            choice: str = input(f"{YELLOW}➡️ Enter 1, 2, 3, or 4: {RESET}")
            print()
            input_method = {"1": "csv", "2": "manual", "3": "export", "4": "quit"}.get(choice)
            if not input_method:
                print(f"{RED}😕 Invalid input, please enter 1, 2, 3, or 4.{RESET}")
                continue
        else:
            valid_methods = ["csv", "manual", "quit"]
            print("  1. Use a CSV file\n  2. Manually enter user details\n  3. Quit\n")
            choice = input(f"{YELLOW}➡️ Enter 1, 2, or 3: {RESET}")
            print()
            input_method = {"1": "csv", "2": "manual", "3": "quit"}.get(choice)
            if not input_method:
                print(f"{RED}😕 Invalid input, please enter 1, 2, or 3.{RESET}")
                continue

        if input_method == "export":
            # Export user list to CSV
            user_list: Optional[List[Dict[str, str]]] = show_user_list("delete")
            if user_list:
                timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_csv: str = f"user_list_{timestamp}.csv"
                with open(output_csv, 'w', newline='') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=["UUID", "Name", "Email", "State"])
                    writer.writeheader()
                    writer.writerows(user_list)
                full_output_path: str = os.path.abspath(output_csv)
                print(f"{CYAN}📊 User list exported to {full_output_path}{RESET}")
            else:
                print(f"{RED}😕 Failed to export user list. Continuing...{RESET}")
            input_method = None
            first_prompt = False
            continue

    if input_method == "quit":
        print(f"{CYAN}👋 Exiting script.{RESET}\n")
        return

    # Get action (provision, suspend, reactivate, delete, or quit)
    valid_actions: List[str] = ["provision", "suspend", "reactivate", "delete", "quit"]
    action: Optional[str] = None
    while not action:
        print(f"\n{YELLOW}📋 What would you like to do?{RESET}")
        print("  1. Provision users (invite to 1Password)\n  2. Suspend users (disable account access)\n  3. Reactivate users (restore account access)\n  4. Delete users (permanently remove)\n  5. Quit\n")
        choice = input(f"{YELLOW}➡️ Enter 1, 2, 3, 4, or 5: {RESET}")
        print()
        action = {"1": "provision", "2": "suspend", "3": "reactivate", "4": "delete", "5": "quit"}.get(choice)
        if not action:
            print(f"{RED}😕 Invalid input, please enter 1, 2, 3, 4, or 5.{RESET}")

    if action == "quit":
        print(f"{CYAN}👋 Exiting script.{RESET}\n")
        return

    results: List[Dict[str, Any]] = []
    if input_method == "csv":
        default_csv: str = "people.csv"
        csv_path: Optional[str] = None
        # Prompt for CSV file path
        while not csv_path:
            print(f"\n{YELLOW}📄 Enter the path to your CSV file (default: {default_csv}, type 'quit' to exit):{RESET}\n")
            input_path: str = input(f"{YELLOW}➡️ Path: {RESET}")
            print()
            if input_path == "quit":
                print(f"{CYAN}👋 Exiting script.{RESET}\n")
                return
            csv_path = input_path or default_csv
            if not os.path.exists(csv_path):
                print(f"{RED}😕 File '{csv_path}' not found. Please try again.{RESET}")
                csv_path = None
                continue

        try:
            # Read and validate CSV data
            csv_data: List[Dict[str, str]] = []
            with open(csv_path, newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                if not reader.fieldnames:
                    print(f"\n{RED}😕 CSV file is empty or missing headers. Please use a valid CSV file.{RESET}")
                    return
                csv_data = [row for row in reader]

            if not csv_data:
                print(f"\n{RED}😕 CSV file contains no data. Please use a valid CSV file.{RESET}")
                return

            # Check required columns
            if action == "provision":
                if not any(col.lower() == "name" for col in reader.fieldnames) or not any(col.lower() == "email" for col in reader.fieldnames):
                    print(f"\n{RED}😕 CSV must have 'Name' and 'Email' columns for provisioning. Please use a valid CSV file.{RESET}")
                    return
            else:
                if not any(col.lower() == "uuid" for col in reader.fieldnames) and not any(col.lower() == "email" for col in reader.fieldnames):
                    print(f"\n{RED}😕 CSV must have either 'UUID' or 'Email' column for {action}. Please use a valid CSV file.{RESET}")
                    return
        except Exception as e:
            print(f"\n{RED}😕 Error reading CSV: {str(e)}. Please use a valid CSV file.{RESET}")
            return

        csv_identifiers: List[str] = []
        csv_names: List[str] = []
        # Extract identifiers and names from CSV
        for row in csv_data:
            if action == "provision":
                name = str(row.get("Name", "")).replace('"', "'")
                email = str(row.get("Email", ""))
                identifier = email
            else:
                uuid = str(row.get("UUID", ""))
                email = str(row.get("Email", ""))
                identifier = uuid or email
                name = str(row.get("Name", ""))
            csv_identifiers.append(identifier)
            csv_names.append(name)

        # Confirm destructive actions
        if action in ["suspend", "reactivate", "delete"]:
            print("\n")
            msg: str = {
                "suspend": "Suspending users disables their account access!",
                "reactivate": "Reactivating users will restore their account access!",
                "delete": "Deleting users and their Private vaults is permanent!"
            }[action]
            print(f"{RED}{BLINK}⚠️ WARNING: {msg}{RESET}\n")
            show_email_list(csv_identifiers, action, csv_names)
            print("\n")
            confirm: str = input(f"{YELLOW}➡️ Type 'YES' to continue, or anything else to cancel: {RESET}")
            print()
            if confirm != "YES":
                print(f"{CYAN}👋 Operation cancelled.{RESET}\n")
                return

        print(f"\n{CYAN}🔧 Processing {len(csv_data)} users for {action}...{RESET}\n")
        result_queue: Queue = Queue()
        threads: List[threading.Thread] = []
        max_threads: int = 3  # Limit to 3 threads to avoid overwhelming the system

        # Process users(branch: main) users in parallel
        for i, row in enumerate(csv_data):
            while len([t for t in threads if t.is_alive()]) >= max_threads:
                time.sleep(0.1)

            if action == "provision":
                name = str(row.get("Name", "")).replace('"', "'")
                identifier = str(row.get("Email", ""))
            else:
                uuid = str(row.get("UUID", ""))
                email = str(row.get("Email", ""))
                identifier = uuid or email
                name = str(row.get("Name", ""))

            thread = threading.Thread(target=process_user, args=(name, identifier, action, result_queue))
            thread.start()
            threads.append(thread)

        # Wait for all threads to finish
        for thread in threads:
            thread.join()

        # Collect results from queue
        while not result_queue.empty():
            results.append(result_queue.get())

    else:
        print(f"\n{CYAN}🔧 Manually managing a user for {action}...{RESET}\n")
        identifiers: List[str] = []

        if action in ["suspend", "reactivate", "delete"]:
            identifier_input: Optional[str] = None
            # Prompt for UUID or email, with option to list users
            while not identifier_input:
                print(f"{YELLOW}📋 Enter the user(s) UUID or email (separate multiple entries with commas, type 'list' to see filtered users, or 'quit' to exit):{RESET}\n")
                identifier_input = input(f"{YELLOW}➡️ UUID(s) or Email(s): {RESET}")
                print()
                if identifier_input == "quit":
                    print(f"{CYAN}👋 Exiting script.{RESET}\n")
                    return
                if identifier_input == "list":
                    user_list = show_user_list(action)
                    if not user_list:
                        print(f"\n{CYAN}👋 No users found. Returning to input prompt.{RESET}\n")
                        identifier_input = None
                        continue
                if not identifier_input:
                    print(f"{RED}😕 UUID or email cannot be empty. Please try again.{RESET}\n")
                    continue
                identifiers = [i.strip() for i in identifier_input.split(",")]
                for identifier in identifiers:
                    if not (re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', identifier) or
                            re.match(r'^[a-zA-Z0-9]{26}$', identifier)):
                        print(f"{RED}😕 Invalid UUID or email format: {identifier}. Please try again.{RESET}\n")
                        identifier_input = None
                        break
        else:
            email_input: Optional[str] = None
            # Prompt for email for provisioning
            while not email_input:
                print(f"{YELLOW}📋 Enter the user's email (type 'quit' to exit):{RESET}\n")
                email_input = input(f"{YELLOW}➡️ Email: {RESET}")
                print()
                if email_input == "quit":
                    print(f"{CYAN}👋 Exiting script.{RESET}\n")
                    return
                if not email_input:
                    print(f"{RED}😕 Email cannot be empty. Please try again.{RESET}\n")
                    continue
                if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email_input):
                    print(f"{RED}😕 Invalid email format: {email_input}. Please try again.{RESET}\n")
                    email_input = None
                    continue
            identifiers = [email_input]

        if action == "provision":
            name: Optional[str] = None
            # Prompt for name for provisioning
            while not name:
                print(f"{YELLOW}📋 Enter the user's name (type 'quit' to exit):{RESET}\n")
                name = input(f"{YELLOW}➡️ Name: {RESET}")
                print()
                if name == "quit":
                    print(f"{CYAN}👋 Exiting script.{RESET}\n")
                    return
                if not name:
                    print(f"{RED}😕 Name cannot be empty. Please try again.{RESET}\n")
                    continue
        else:
            name = "Unknown"

        if action in ["suspend", "reactivate", "delete"]:
            user_details: List[Dict[str, Any]] = []
            result_queue = Queue()
            threads = []

            # Fetch user info for each identifier
            for identifier in identifiers:
                while len([t for t in threads if t.is_alive()]) >= 3:
                    time.sleep(0.1)

                def get_user_info(identifier: str, queue: Queue) -> None:
                    # Get user details from 1Password CLI
                    op_result: Tuple[bool, str] = invoke_op_command(["user", "get", identifier])
                    name: str = "Unknown"
                    email: str = identifier
                    if op_result[0]:
                        # Parse name and email from CLI output
                        name_match = re.search(r"Name:\s*([^\n]+)", op_result[1])
                        email_match = re.search(r"Email:\s*([^\n]+)", op_result[1])
                        if name_match:
                            name = name_match.group(1).strip()
                        if email_match:
                            email = email_match.group(1).strip()
                    queue.put({
                        "Identifier": identifier,
                        "Name": name,
                        "Email": email,
                        "Exists": op_result[0],
                        "ErrorMessage": op_result[1] if not op_result[0] else None
                    })

                thread = threading.Thread(target=get_user_info, args=(identifier, result_queue))
                thread.start()
                threads.append(thread)

            # Wait for user info threads to finish
            for thread in threads:
                thread.join()

            # Collect user details from queue
            while not result_queue.empty():
                user_details.append(result_queue.get())

            # Handle users that don't exist
            failed_users: List[Dict[str, Any]] = [u for u in user_details if not u["Exists"]]
            if failed_users:
                for failed_user in failed_users:
                    results.append({
                        "Name": failed_user["Name"],
                        "Email": failed_user["Identifier"],
                        "Status": "Failed",
                        "FullMessage": failed_user["ErrorMessage"]
                    })
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_csv = f"{action}_{timestamp}.csv"
                with open(output_csv, 'w', newline='') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=["Name", "Email", "Status", "FullMessage"])
                    writer.writeheader()
                    writer.writerows(results)
                full_output_path = os.path.abspath(output_csv)
                print("\n")
                show_table(results)
                print(f"\n{CYAN}📊 {action} completed! Results saved to {full_output_path}{RESET}\n")
                print(f"{GREEN}🎈 All done! Check the CSV for details.{RESET}\n")
                return

            identifiers = [u["Email"] for u in user_details]
            name = user_details[0]["Name"] if user_details else name

        # Confirm destructive actions for manual input
        if action in ["suspend", "reactivate", "delete"]:
            print("\n")
            msg = {
                "suspend": f"Suspending user(s) '{', '.join(identifiers)}' will disable their account access!",
                "reactivate": f"Reactivating user(s) '{', '.join(identifiers)}' will restore their account access!",
                "delete": f"Deleting user(s) '{', '.join(identifiers)}' and their Private vaults is permanent!"
            }[action]
            print(f"{RED}{BLINK}⚠️ WARNING: {msg}{RESET}\n")
            show_email_list(identifiers, action)
            print("\n")
            confirm = input(f"{YELLOW}➡️ Type 'YES' to continue, or anything else to cancel: {RESET}")
            print()
            if confirm != "YES":
                print(f"{CYAN}👋 Operation cancelled.{RESET}\n")
                return

        print(f"\n{CYAN}🔧 Processing user(s) for {action}...{RESET}\n")
        result_queue = Queue()
        threads = []

        # Process each user in a separate thread
        for identifier in identifiers:
            while len([t for t in threads if t.is_alive()]) >= 3:
                time.sleep(0.1)

            thread = threading.Thread(target=process_user, args=(name, identifier, action, result_queue))
            thread.start()
            threads.append(thread)

        # Wait for all processing threads to finish
        for thread in threads:
            thread.join()

        # Collect results from queue
        while not result_queue.empty():
            results.append(result_queue.get())

    # Save results to a CSV file
    timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv: str = f"{action}_{timestamp}.csv"
    with open(output_csv, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["Name", "Email", "Status", "FullMessage"])
        writer.writeheader()
        writer.writerows(results)
    full_output_path: str = os.path.abspath(output_csv)

    # Display results and wrap up
    show_table(results)
    print(f"\n{CYAN}📊 {action} completed! Results saved to {full_output_path}{RESET}\n")
    print(f"{GREEN}🎈 All done! Check the CSV for details.{RESET}\n")

if __name__ == "__main__":
    main()