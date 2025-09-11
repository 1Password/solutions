import subprocess
import os
import sys
from typing import List, Dict, Any, Tuple

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

def show_table(headers: List[str], data: List[Dict[str, Any]], max_message_length: int = 30) -> None:
    # Print a neat table with Name, Email, Status, and Message
    if not data:
        print(f"\n{YELLOW}😕 No data to display.{RESET}")
        return

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

def main() -> None:
    # Print script information
    print(f"\n{CYAN}🚀 Welcome to the 1Password ... Script! 🎉{RESET}")
    print("This script ...\n")

    # Ensure we're authenticated before starting
    if not check_op_auth():
        sys.exit(1)

    # Your code starts here


if __name__ == "__main__":
    main()