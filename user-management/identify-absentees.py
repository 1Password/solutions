import subprocess
import json
import csv
import re
import os
from datetime import datetime
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor

# Try to import tqdm for a nice progress bar, but it’s optional
try:
    import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

def run_op_command(args: List[str]) -> Dict[str, Any]:
    # Runs a 1Password CLI command and returns JSON output
    # Assumes we're already logged in, so no fuss with tokens
    cmd = ["op"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout) if result.stdout else {}
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  Whoops, hit a snag running {' '.join(cmd)}: {e.stderr}")
        raise
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON didn’t parse right: {e}")
        raise

def parse_user_list_output() -> List[Dict[str, str]]:
    # Grabs the user list from 1Password’s non-JSON output and parses it
    # The output is tabular, so we split it into fields
    try:
        result = subprocess.run(
            ["op", "user", "list"],
            capture_output=True,
            text=True,
            check=True
        )
        lines = result.stdout.splitlines()
        users = []
        # Skip empty lines and header
        data_lines = [line for line in lines[1:] if line.strip()]
        for line in data_lines:
            # Split on multiple spaces (approximating PowerShell’s split)
            fields = re.split(r'\s{2,}', line.strip())
            if len(fields) >= 4:  # Expect at least ID, NAME, EMAIL, STATE
                users.append({
                    "id": fields[0],
                    "name": fields[1],
                    "email": fields[2],
                    "state": fields[3]
                })
        return users
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  Couldn’t fetch user list: {e.stderr}")
        raise

def fetch_user_details(user: Dict[str, str]) -> Optional[Dict[str, Any]]:
    # Fetches detailed info for a single user, used in threads
    try:
        details = run_op_command(["user", "get", user["id"], "--format=json"])
        # Merge basic info with details
        details.update({
            "id": user["id"],
            "name": user.get("name", ""),
            "email": user["email"]
        })
        return details
    except subprocess.CalledProcessError:
        print(f"  ⚠️  Couldn’t grab details for user {user['id']}. Skipping.")
        return None

def get_active_users() -> List[Dict[str, Any]]:
    # Gets all active users, fetching details in parallel with 3 threads
    users = parse_user_list_output()
    active_users = [u for u in users if u["state"] == "ACTIVE"]
    print(f"  🎉 Found {len(active_users)} active users!")
    
    # Fetch details in parallel
    print("\n🔍 Checking user activity...")
    with ThreadPoolExecutor(max_workers=3) as executor:
        if TQDM_AVAILABLE:
            # Use tqdm for a fancy progress bar if available
            results = list(tqdm.tqdm(
                executor.map(fetch_user_details, active_users),
                total=len(active_users),
                desc="Processing users",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} users"
            ))
        else:
            # Fallback to a simple counter if tqdm isn’t installed
            print("  (No progress bar; install tqdm with 'pip install tqdm' for one!)")
            results = []
            for i, result in enumerate(executor.map(fetch_user_details, active_users), 1):
                results.append(result)
                print(f"  Processed {i}/{len(active_users)} users...", end="\r")
            print()  # Clear the line
    # Filter out None results (failed fetches)
    return [r for r in results if r is not None]

def parse_date(date_str: str) -> Optional[datetime]:
    # Tries to parse dates in ISO 8601 or MM/dd/yyyy formats
    iso8601_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
    us_date_pattern = r'^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}$'
    
    try:
        if re.match(iso8601_pattern, date_str):
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        elif re.match(us_date_pattern, date_str):
            return datetime.strptime(date_str, "%m/%d/%Y %H:%M:%S")
        else:
            return None
    except ValueError:
        return None

def print_boxed_summary(days: int, total_users: int, active_users: int, error: Optional[str] = None) -> None:
    # Prints a fancy boxed summary of the initial scan
    header = "Checking User Activity..."
    days_line = f"Days Threshold: {days}"
    total_line = f"Total Users Found: {total_users}" if not error else f"Error: {error}"
    active_line = f"Active Users: {active_users}"
    
    # Find the longest line for padding
    lines = [header, days_line, total_line, active_line]
    max_length = max(len(line) for line in lines)
    padding = max_length + 2  # 1 space on each side
    
    # Build the box
    top_border = "┌" + ("─" * padding) + "┐"
    mid_border = "├" + ("─" * padding) + "┤"
    bottom_border = "└" + ("─" * padding) + "┘"
    
    # Print it out
    print("\n" + top_border)
    print(f"│ {header.ljust(max_length)} │")
    print(mid_border)
    print(f"│ {days_line.ljust(max_length)} │")
    print(f"│ {total_line.ljust(max_length)} │" if not error else f"│ {total_line.ljust(max_length)} │")
    print(f"│ {active_line.ljust(max_length)} │")
    print(bottom_border)

def print_idle_users_table(idle_users: List[Dict[str, Any]]) -> None:
    # Prints a formatted table of idle users
    if not idle_users:
        print("\n🎉 Nobody’s been idle too long. Everyone’s active!")
        return
    
    print("\nHere’s who’s been away for a while:")
    
    # Column headers
    email_header = "E-mail"
    days_header = "Days Idle"
    login_header = "Last Login"
    
    # Calculate max lengths for each column
    email_max = max(max(len(u["email"]) for u in idle_users), len(email_header)) + 2
    days_max = max(max(len(str(u.get("days_idle", ""))) for u in idle_users), len(days_header)) + 2
    login_max = max(max(len(u.get("last_auth_at", "")) for u in idle_users), len(login_header)) + 2
    
    # Build the table borders
    top_border = "┌" + ("─" * email_max) + "┬" + ("─" * days_max) + "┬" + ("─" * login_max) + "┐"
    header_row = f"│ {email_header.ljust(email_max-2)} │ {days_header.ljust(days_max-2)} │ {login_header.ljust(login_max-2)} │"
    mid_border = "├" + ("─" * email_max) + "┼" + ("─" * days_max) + "┼" + ("─" * login_max) + "┤"
    bottom_border = "└" + ("─" * email_max) + "┴" + ("─" * days_max) + "┴" + ("─" * login_max) + "┘"
    
    # Print the table
    print(top_border)
    print(header_row)
    print(mid_border)
    for user in idle_users:
        email = user["email"].ljust(email_max-2)
        days = str(user.get("days_idle", "")).ljust(days_max-2)
        login = user.get("last_auth_at", "").ljust(login_max-2)
        print(f"│ {email} │ {days} │ {login} │")
    print(bottom_border)

def main() -> None:
    # Main logic: find idle users and report them
    print("\n🚀 Let’s find those idle 1Password users...")
    
    # Ask how many days counts as idle
    try:
        days = int(input("\nHow many days since last login makes someone idle? "))
    except ValueError:
        print("  ⚠️  Please enter a valid number!")
        return
    
    # Step 1: Get the user list and summarize
    print("\n📋 Scanning users...")
    try:
        users = parse_user_list_output()
        total_users = len(users)
        active_users = len([u for u in users if u["state"] == "ACTIVE"])
        print_boxed_summary(days, total_users, active_users)
        print()  # Add a blank line after the box
    except subprocess.CalledProcessError:
        print_boxed_summary(days, 0, 0, "Failed to fetch user list")
        return
    
    # Step 2: Fetch details for active users
    active_users = get_active_users()
    if not active_users:
        print("\n😕 No active users to check. Done!")
        return
    
    # Step 3: Find idle users
    print("\n🔎 Hunting for idle users...")
    threshold_seconds = days * 86400
    now = datetime.utcnow()
    idle_users = []
    
    # Sort active users by days idle (descending) before processing
    active_users.sort(key=lambda x: (
        float('inf') if x.get("last_auth_at") in ["0001-01-01T00:00:00Z", "01/01/0001 00:00:00"]
        else float('inf') if not x.get("last_auth_at")
        else (now - parse_date(x["last_auth_at"])).total_seconds() / 86400
        if parse_date(x.get("last_auth_at"))
        else 0
    ), reverse=True)
    
    for user in active_users:
        last_auth_at = user.get("last_auth_at", "")
        if not last_auth_at:
            print(f"  {user['email'].ljust(50)} No login date, skipping.")
            continue
        
        # Handle "never logged in" cases
        if last_auth_at in ["0001-01-01T00:00:00Z", "01/01/0001 00:00:00"]:
            print(f"  {user['email'].ljust(50)} Never logged in")
            user["days_idle"] = "Never logged in"
            idle_users.append(user)
            continue
        
        # Parse the last login date
        last_login = parse_date(last_auth_at)
        if not last_login:
            print(f"  {user['email'].ljust(50)} Weird date format ('{last_auth_at}'), skipping.")
            continue
        
        # Calculate days since last login
        diff_seconds = (now - last_login).total_seconds()
        diff_days = round(diff_seconds / 86400, 1)
        color = "\033[31m" if diff_days > days else "\033[32m"  # Red for idle, green for active
        reset = "\033[0m"
        print(f"  {user['email'].ljust(50)} {color}{diff_days} days since login{reset}")
        
        if diff_days > days:
            user["days_idle"] = diff_days
            idle_users.append(user)
    
    # Step 4: Save to CSV
    csv_path = os.path.abspath("user_list.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["UUID", "Name", "E-mail", "Last_Login_Date"])
        for user in idle_users:
            writer.writerow([user["id"], user["name"], user["email"], user.get("last_auth_at", "")])
    
    # Step 5: Show the idle users table
    print_idle_users_table(idle_users)
    
    print(f"\n🎈 All done! Check {csv_path} for the full list.")

if __name__ == "__main__":
    main()