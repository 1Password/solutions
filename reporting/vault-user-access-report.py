#!/usr/bin/env python3
import os
import subprocess
import csv
import json
import argparse
import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Argument parser
parser = argparse.ArgumentParser(
    description="Generates a CSV report of users and groups with their permissions for each vault.",
)
parser.add_argument(
    "--file",
    type=Path,
    dest="filepath",
    help="Path to a file containing a line-delimited list of vault UUIDs.",
)
parser.add_argument(
    "--output",
    type=Path,
    default="output.csv",
    help="Path to the output CSV file (default: output.csv).",
)
parser.add_argument(
    "--quiet",
    action="store_true",
    help="Suppress console output.",
)
args = parser.parse_args()


def check_cli_version() -> None:
    """Check if the 1Password CLI version is 2.25 or greater."""
    try:
        result = subprocess.run(
            ["op", "--version", "--format=json"],
            capture_output=True,
            text=True,
            check=True,
        )
        version = result.stdout.strip()
        major, minor = map(int, version.split(".", 2)[:2])
        if major < 2 or (major == 2 and minor < 25):
            sys.exit(
                "❌ 1Password CLI version must be 2.25 or greater. "
                "See https://developer.1password.com/docs/cli/get-started."
            )
    except (subprocess.CalledProcessError, ValueError) as e:
        sys.exit(f"❌ Failed to check CLI version: {e}")


def run_op_command(args: List[str]) -> Dict:
    """Run a 1Password CLI command and return parsed JSON output."""
    try:
        result = subprocess.run(
            ["op"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"Command 'op {' '.join(args)}' failed: {e.stderr}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON output from 'op {' '.join(args)}': {e}")
        raise


def get_vaults(filepath: Optional[Path]) -> List[Dict]:
    """Get a list of vaults, either from a file or all vaults with manage_vault permission."""
    if filepath:
        try:
            with filepath.open("r", encoding="utf-8") as f:
                vault_ids = [line.strip() for line in f if line.strip()]
            # Fetch all vaults and filter by UUID
            all_vaults = run_op_command(["vault", "list", "--format=json"])
            return [vault for vault in all_vaults if vault["id"] in vault_ids]
        except FileNotFoundError:
            sys.exit(f"❌ Input file not found: {filepath}")
        except Exception as e:
            sys.exit(f"❌ Failed to process input file {filepath}: {e}")
    else:
        try:
            return run_op_command(["vault", "list", "--permission=manage_vault", "--format=json"])
        except Exception as e:
            sys.exit(
                "❌ Unable to fetch vaults. Ensure you are signed in as an Owner "
                "or provide a list of vault UUIDs using --file."
            )


def write_report(vaults: List[Dict], output_path: Path, quiet: bool) -> None:
    """Write user and group permissions for each vault to a CSV file."""
    fields = [
        "vaultName",
        "vaultUUID",
        "type",
        "userName",
        "groupName",
        "email",
        "userOrGroupUUID",
        "permissions",
    ]
    
    try:
        with output_path.open("w", newline="", encoding="utf-8") as output_file:
            csv_writer = csv.writer(output_file)
            csv_writer.writerow(fields)

            for vault in vaults:
                vault_id = vault["id"]
                vault_name = vault["name"]

                # Fetch users
                try:
                    users = run_op_command(["vault", "user", "list", vault_id, "--format=json"])
                    for user in users:
                        row = [
                            vault_name,
                            vault_id,
                            "user",
                            user["name"],
                            None,
                            user["email"],
                            user["id"],
                            user["permissions"],
                        ]
                        csv_writer.writerow(row)
                        if not quiet:
                            logger.info(f"User: {vault_name}, {user['name']}, {user['email']}, {user['permissions']}")
                except Exception as e:
                    logger.error(f"Failed to fetch users for vault {vault_name} ({vault_id}): {e}")

                # Fetch groups
                try:
                    groups = run_op_command(["vault", "group", "list", vault_id, "--format=json"])
                    for group in groups:
                        row = [
                            vault_name,
                            vault_id,
                            "group",
                            None,
                            group["name"],
                            None,
                            group["id"],
                            group["permissions"],
                        ]
                        csv_writer.writerow(row)
                        if not quiet:
                            logger.info(f"Group: {vault_name}, {group['name']}, {group['permissions']}")
                except Exception as e:
                    logger.error(f"Failed to fetch groups for vault {vault_name} ({vault_id}): {e}")

    except PermissionError:
        sys.exit(f"❌ Permission denied when writing to {output_path}")
    except Exception as e:
        sys.exit(f"❌ Failed to write output file {output_path}: {e}")


def main() -> None:
    """Main function to generate the vault permissions report."""
    check_cli_version()
    vaults = get_vaults(args.filepath)
    write_report(vaults, args.output, args.quiet)
    logger.info(f"Report generated successfully: {args.output}")


if __name__ == "__main__":
    main()