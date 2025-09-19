#!/usr/bin/env python3

import csv
import json
import subprocess
import sys
import os


def run_op_command(command_args):
    """
    Runs an 'op' command and returns its stdout.
    Raises subprocess.CalledProcessError on failure.
    """
    try:
        # Ensure OP_CONNECT_HOST and OP_CONNECT_TOKEN are not set if using biometric unlock
        # or normal op sign-in, as they are for 1Password Connect.
        # However, if the user *is* using Connect, they should have these set.
        # For general CLI usage, it's better not to interfere with existing env vars
        # unless specifically managing Connect tokens.
        # For this script, we assume standard 'op' CLI usage.

        process = subprocess.run(
            command_args,
            capture_output=True,
            text=True,
            check=True,  # Raises CalledProcessError for non-zero exit codes
            encoding="utf-8",
        )
        return process.stdout.strip()
    except subprocess.CalledProcessError as e:
        # The error will be caught by the caller, which can print stderr
        raise e
    except FileNotFoundError:
        print(
            "Error: The 'op' command-line tool was not found. "
            "Please ensure it is installed and in your PATH.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            f"An unexpected error occurred while trying to run 'op' command: {e}",
            file=sys.stderr,
        )
        raise e


def find_concealed_field_assignment_key(item_data):
    """
    Finds the assignment key for the concealed field to update.
    Prioritizes the primary password field, then the first generic concealed field.
    Returns the assignment key (e.g., "password" or "Section.Label") or None.
    """
    if not item_data or "fields" not in item_data:
        return None

    primary_password_field = None
    first_concealed_field = None

    for field in item_data.get("fields", []):
        if field.get("type") == "CONCEALED":
            if field.get("purpose") == "PASSWORD":
                primary_password_field = field
                break  # Found the primary password, no need to look further
            if not first_concealed_field:
                first_concealed_field = field

    target_field = (
        primary_password_field if primary_password_field else first_concealed_field
    )

    if not target_field:
        return None

    field_label = target_field.get("label")
    if not field_label:
        # Fallback if label is missing, though unlikely for well-formed items
        # The 'id' might sometimes be used as a fallback designator by 'op'
        # but 'label' is the primary way for 'op item edit'.
        # If label is missing, this field is likely problematic to edit by label.
        print(
            f"Warning: Concealed field found with ID '{target_field.get('id')}' but no label. Skipping.",
            file=sys.stderr,
        )
        return None

    if "section" in target_field and target_field["section"].get("label"):
        section_label = target_field["section"]["label"]
        return f"{section_label}.{field_label}"
    else:
        return field_label


def update_password_from_csv(csv_filepath):
    """
    Loads a CSV file and updates 1Password items based on its content.
    """
    try:
        with open(
            csv_filepath, mode="r", encoding="utf-8-sig"
        ) as csvfile:  # utf-8-sig handles BOM
            reader = csv.DictReader(csvfile)

            # Check for required headers
            required_headers = ["vault", "item title", "new password"]
            if not all(header in reader.fieldnames for header in required_headers):
                missing = [h for h in required_headers if h not in reader.fieldnames]
                print(
                    f"Error: CSV file is missing required headers: {', '.join(missing)}",
                    file=sys.stderr,
                )
                print(
                    f"Expected headers: {', '.join(required_headers)}", file=sys.stderr
                )
                print(f"Found headers: {', '.join(reader.fieldnames)}", file=sys.stderr)
                return False

            for i, row in enumerate(reader):
                line_num = i + 2  # For user-friendly line numbers (1-based + header)
                try:
                    vault_name = row["vault"]
                    item_title = row["item title"]
                    new_password = row["new password"]

                    if not all([vault_name, item_title, new_password]):
                        print(
                            f"Warning: Skipping CSV line {line_num} due to missing values "
                            f"(vault, item title, or new password).",
                            file=sys.stderr,
                        )
                        continue

                    print(
                        f"\nProcessing CSV line {line_num}: Vault='{vault_name}', Item='{item_title}'"
                    )

                    # 1. Fetch the item
                    print(
                        f"  Fetching item '{item_title}' from vault '{vault_name}'..."
                    )
                    item_json_str = run_op_command(
                        [
                            "op",
                            "item",
                            "get",
                            item_title,
                            "--vault",
                            vault_name,
                            "--format",
                            "json",
                        ]
                    )
                    item_data = json.loads(item_json_str)

                    # 2. Find the concealed field's assignment key
                    assignment_key_base = find_concealed_field_assignment_key(item_data)
                    if not assignment_key_base:
                        print(
                            f"  Error: Could not find a suitable concealed field for item '{item_title}'. Skipping.",
                            file=sys.stderr,
                        )
                        continue

                    print(f"  Identified field to update: '{assignment_key_base}'")

                    # 3. Update the item
                    # The assignment format is "field_key=value"
                    # Example: "password=newsecret" or "Section Name.Custom Password=newsecret"
                    field_assignment = f"{assignment_key_base}={new_password}"

                    print(
                        f"  Updating field '{assignment_key_base}' for item '{item_title}'..."
                    )
                    run_op_command(
                        [
                            "op",
                            "item",
                            "edit",
                            item_title,
                            "--vault",
                            vault_name,
                            field_assignment,
                        ]
                    )
                    print(
                        f"  Successfully updated password for '{item_title}' in vault '{vault_name}'."
                    )

                except subprocess.CalledProcessError as e:
                    print(
                        f"  Error processing item '{item_title}' in vault '{vault_name}' (CSV line {line_num}):",
                        file=sys.stderr,
                    )
                    print(f"    Command: {' '.join(e.cmd)}", file=sys.stderr)
                    print(
                        f"    Stderr: {e.stderr.strip() if e.stderr else 'N/A'}",
                        file=sys.stderr,
                    )
                    # op might also print useful info to stdout on error
                    if e.stdout:
                        print(f"    Stdout: {e.stdout.strip()}", file=sys.stderr)
                except json.JSONDecodeError:
                    print(
                        f"  Error: Could not parse JSON output for item '{item_title}'. Skipping.",
                        file=sys.stderr,
                    )
                except KeyError as e:
                    print(
                        f"  Error: CSV line {line_num} is missing an expected column: {e}. Please check CSV format.",
                        file=sys.stderr,
                    )
                except Exception as e:
                    print(
                        f"  An unexpected error occurred for item '{item_title}' (CSV line {line_num}): {e}",
                        file=sys.stderr,
                    )
        return True

    except FileNotFoundError:
        print(f"Error: CSV file not found at '{csv_filepath}'", file=sys.stderr)
        return False
    except Exception as e:
        print(
            f"An unexpected error occurred while reading or processing the CSV file: {e}",
            file=sys.stderr,
        )
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python update_op_passwords.py <path_to_csv_file>")
        print("The CSV file must contain the headers: vault, item title, new password")
        sys.exit(1)

    csv_file_path = sys.argv[1]
    print(f"Starting 1Password item update process using CSV: {csv_file_path}")

    # Basic check for 'op' CLI sign-in status
    try:
        run_op_command(
            ["op", "account", "list"]
        )  # A simple command to check if op is working and signed in
        print("Successfully connected to 1Password CLI.")
    except subprocess.CalledProcessError as e:
        print(
            "Error: 1Password CLI 'op account list' command failed. "
            "Please ensure you are signed in to the 1Password CLI.",
            file=sys.stderr,
        )
        if e.stderr:
            print(f"Details: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:  # Already handled in run_op_command, but good for clarity
        sys.exit(1)  # Message printed by run_op_command

    if update_password_from_csv(csv_file_path):
        print("\nPassword update process completed.")
    else:
        print("\nPassword update process completed with errors.", file=sys.stderr)
        sys.exit(1)
