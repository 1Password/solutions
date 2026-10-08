#!/usr/bin/env python3
"""Writes a CSV of who has access to each vault and with which permissions.

Looks up who has access to every vault you can manage (or only the vaults listed
in --file) and writes it to vault_access_report.csv next to this script. Nothing
inside the vaults is read or copied, only the access. There's one row for each
user assigned directly to a vault, and one row for each member of each group
assigned to a vault, with that assignment's permissions.

The Employee vault is skipped. Vaults are read 10 at a time, and each op command
is retried up to 3 times. Anything that still can't be read goes in
logs/mapping_<timestamp>/errors.log, and the script exits with 1 so you know the
CSV is missing something.

The CSV can be fed to recreate_vault_permissions.py (or the PowerShell version)
to set the same access up in another account.

Options:
  --file     Optional. Only checks the vaults listed in this file: a plain text
             file you write yourself with one vault ID per line. This is only
             read, the results always go to vault_access_report.csv.
  --account  The 1Password account to use (sign-in address or shorthand), if
             you're signed in to more than one.

Examples:
  python3 shared_vaults_permissions_mapping.py
  python3 shared_vaults_permissions_mapping.py --file vault-ids.txt --account mycompany

Requires Python 3.9 or later and the 1Password CLI v2.25 or later, signed in.
The CSV has names and email addresses in it, so keep it out of source control.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR / "vault_access_report.csv"
THREADS = 10
MAX_RETRIES = 3
OP_TIMEOUT_SECONDS = 30
EXCLUDED_VAULTS = {"Employee"}
CSV_COLUMNS = ["vaultName", "vaultUUID", "userName", "groupName", "email", "userUUID",
               "assignment", "status", "permissions"]

PERMANENT_ERRORS = [
    "does not have access",
    "not found",
    "isn't a vault",
    "isn't a group",
    "not authorized",
    "no accounts for filter",
]

IS_TTY = sys.stdout.isatty()
USE_COLOR = IS_TTY and not os.environ.get("NO_COLOR")
BOLD, DIM, RED, GREEN, YELLOW, CYAN, RESET = (
    ("\033[1m", "\033[2m", "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[0m")
    if USE_COLOR else ("",) * 7
)

_run_started = datetime.now()
_logs_dir = SCRIPT_DIR / "logs" / f"mapping_{_run_started.strftime('%Y-%m-%d_%H-%M-%S')}"
_errors_path = _logs_dir / "errors.log"
_log_lock = threading.Lock()
_progress = {"label": "", "done": 0, "total": 0, "started": 0.0}
_error_count = 0
_account: Optional[str] = None


# Draws the progress bar with a time estimate, only when running in a terminal
def draw_progress() -> None:
    if not IS_TTY or not _progress["total"]:
        return
    done, total = _progress["done"], _progress["total"]
    width = 24
    filled = int(width * done / total)
    bar = "█" * filled + "░" * (width - filled)
    eta = ""
    if 0 < done < total:
        elapsed = time.time() - _progress["started"]
        eta = f"  {DIM}about {elapsed / done * (total - done):.0f}s left{RESET}"
    sys.stdout.write(f"\r  {_progress['label']:<22} {CYAN}{bar}{RESET} {done}/{total}{eta}\033[K")
    sys.stdout.flush()


# Starts a new progress bar
def start_progress(label: str, total: int) -> None:
    _progress.update(label=label, done=0, total=total, started=time.time())
    draw_progress()


# Moves the progress bar forward by one
def step_progress() -> None:
    with _log_lock:
        _progress["done"] += 1
        draw_progress()


# Clears the progress bar and leaves a finished line in its place
def end_progress(result: str) -> None:
    if IS_TTY and _progress["total"]:
        sys.stdout.write("\r\033[K")
    print(f"  {_progress['label']:<22} {result}")
    _progress["total"] = 0


# Prints a section heading
def heading(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# Prints a label and value lined up with the rest of the section
def field(label: str, value) -> None:
    print(f"  {label:<22} {value}")


# Prints an error and stops the script
def stop(message: str) -> None:
    print(f"{RED}{message}{RESET}", file=sys.stderr)
    sys.exit(1)


# Writes a timestamped entry to the error log
def write_error_log(status: str, subject: str, detail: str) -> None:
    global _error_count
    with _log_lock:
        if status == "FAILED":
            _error_count += 1
        if not _errors_path.exists():
            return
        with _errors_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')}  {status:<12} {subject}\n{'':<24}{detail}\n")


# Runs an op command, retrying up to MAX_RETRIES times unless the error won't go away
def run_op(args: list, what: str) -> tuple:
    cmd = ["op"] + args + (["--account", _account] if _account else [])
    err = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=OP_TIMEOUT_SECONDS)
            if r.returncode == 0:
                return True, r.stdout, ""
            err = re.sub(r"^\[ERROR\]\s*(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\s*)?", "", r.stderr.strip())
        except subprocess.TimeoutExpired:
            err = f"timed out after {OP_TIMEOUT_SECONDS}s"
        except Exception as exc:
            err = str(exc)
        if attempt == MAX_RETRIES or any(p in err.lower() for p in PERMANENT_ERRORS):
            break
        write_error_log(f"RETRY {attempt + 1}/{MAX_RETRIES}", what, err)
        time.sleep(2 ** attempt)
    return False, "", err


# Turns op's JSON output into a list, treating empty output as an empty list
def parse_json(text: str) -> list:
    return json.loads(text) if text and text.strip() else []


# Stops early unless the CLI is at least version 2.25
def check_cli_version() -> str:
    ok, stdout, err = run_op(["--version"], "check the CLI version")
    if not ok:
        stop(f"Couldn't check the 1Password CLI version: {err}")
    version = stdout.strip()
    try:
        major, minor = (int(p) for p in version.split(".")[:2])
    except ValueError:
        stop(f"Couldn't read the 1Password CLI version: {version}")
    if major != 2 or minor < 25:
        stop("Requires 1Password CLI v2.25 or higher. See https://developer.1password.com/docs/cli/get-started.")
    return version


# Shows who we're running as and stops if the CLI isn't signed in
def show_header(cli_version: str, file: Optional[str]) -> dict:
    ok, stdout, err = run_op(["whoami", "--format=json"], "whoami")
    if not ok:
        stop(f"Not signed in to 1Password ({err}). Run op signin first.")
    me = json.loads(stdout)
    title = "Vault permissions mapping"
    line = "─" * (len(title) + 4)
    print(f"\n{CYAN}╭{line}╮{RESET}\n{CYAN}│{RESET}  {BOLD}{title}{RESET}  {CYAN}│{RESET}\n{CYAN}╰{line}╯{RESET}")
    print(f"  {DIM}{'Account':<11}{RESET}{me.get('url', '?').replace('https://', '').rstrip('/')}")
    print(f"  {DIM}{'Signed in':<11}{RESET}{me.get('email', '?')}")
    print(f"  {DIM}{'CLI':<11}{RESET}{cli_version}")
    print(f"  {DIM}{'Vaults':<11}{RESET}{f'listed in {file}' if file else 'every vault you can manage'}")
    return me


# Gets the vaults to check, either every vault we can manage or the IDs listed in --file
def get_vaults(file: Optional[str]) -> list:
    if not file:
        ok, stdout, err = run_op(["vault", "list", "--permission=manage_vault", "--format=json"], "list vaults")
        if not ok:
            stop(f"Couldn't list vaults: {err}")
        return [v for v in parse_json(stdout) if v["name"] not in EXCLUDED_VAULTS]

    path = Path(file)
    if not path.exists():
        stop(f"Can't find {file}.")
    vaults = []
    for vault_id in [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]:
        ok, stdout, err = run_op(["vault", "get", vault_id, "--format=json"], f"get vault {vault_id}")
        if not ok:
            stop(f"Couldn't load vault {vault_id}: {err}")
        vault = json.loads(stdout)
        if vault["name"] not in EXCLUDED_VAULTS:
            vaults.append(vault)
    return vaults


# Lists the direct users and groups on one vault
def fetch_vault_access(vault: dict) -> dict:
    entry = {"users": [], "groups": []}
    for part in ("users", "groups"):
        kind = part[:-1]
        ok, stdout, err = run_op(["vault", kind, "list", vault["id"], "--format=json"], f"list {part} on {vault['name']}")
        if ok:
            entry[part] = parse_json(stdout)
        else:
            write_error_log("FAILED", f"list {part} on {vault['name']}", err)
    return entry


# Reads the direct users and groups on every vault, 10 at a time
def read_vault_access(vaults: list) -> dict:
    access = {}
    start_progress("Reading vaults", len(vaults))
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(fetch_vault_access, v): v for v in vaults}
        for future in as_completed(futures):
            access[futures[future]["id"]] = future.result()
            step_progress()
    end_progress(f"{len(vaults)} vaults")
    return access


# Lists the members of one group
def fetch_group_members(group_id: str, group_name: str) -> list:
    ok, stdout, err = run_op(["group", "user", "list", group_id, "--format=json"], f"list members of {group_name}")
    if not ok:
        write_error_log("FAILED", f"list members of {group_name}", err)
        return []
    return parse_json(stdout)


# Reads the members of every group that's on at least one vault, 10 at a time
def read_group_members(access: dict) -> dict:
    groups = {g["id"]: g["name"] for entry in access.values() for g in entry["groups"]}
    members = {}
    if not groups:
        return members
    start_progress("Reading groups", len(groups))
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(fetch_group_members, gid, name): gid for gid, name in groups.items()}
        for future in as_completed(futures):
            members[futures[future]] = future.result()
            step_progress()
    end_progress(f"{len(groups)} groups")
    return members


# Writes the CSV, one row per direct user and one per member of each group on each vault
def write_report(vaults: list, access: dict, members: dict) -> list:
    rows = []
    for vault in vaults:
        entry = access.get(vault["id"], {"users": [], "groups": []})
        for user in entry["users"]:
            rows.append([vault["name"], vault["id"], user.get("name"), "", user.get("email"), user.get("id"),
                         "Direct", user.get("state"), str(user.get("permissions", []))])
        for group in entry["groups"]:
            for member in members.get(group["id"], []):
                rows.append([vault["name"], vault["id"], member.get("name"), group["name"], member.get("email"),
                             member.get("id"), f"Group ({group['name']})", member.get("state"),
                             str(group.get("permissions", []))])
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    return rows


# Reads the options and runs the whole thing
def main() -> None:
    global _account
    ap = argparse.ArgumentParser(description="Write a CSV of who has access to each vault and with which permissions.")
    ap.add_argument("--file", help="A text file with one vault ID per line, to only check those vaults")
    ap.add_argument("--account", help="1Password account shorthand or sign-in address")
    args = ap.parse_args()
    _account = args.account

    version = check_cli_version()
    me = show_header(version, args.file)
    _logs_dir.mkdir(parents=True, exist_ok=True)
    _errors_path.write_text(
        f"Vault permissions mapping\nStarted    {_run_started.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Signed in  {me.get('email', '?')}\nAccount    {me.get('url', '?')}\n\n", encoding="utf-8")

    heading("Reading")
    vaults = get_vaults(args.file)
    if not vaults:
        print(f"  {DIM}No vaults to process{RESET}\n")
        return
    field("Vaults found", len(vaults))
    access = read_vault_access(vaults)
    members = read_group_members(access)

    rows = write_report(vaults, access, members)
    direct = sum(1 for r in rows if r[6] == "Direct")
    took = (datetime.now() - _run_started).total_seconds()
    with _errors_path.open("a", encoding="utf-8") as f:
        f.write(f"\nFinished   {_error_count} failed\n" if _error_count else "\nNo errors.\n")

    heading("Summary")
    print(f"  {GREEN}✓{RESET} {'Vaults':<26}{len(vaults):>5}")
    print(f"  {GREEN}✓{RESET} {'Direct assignments':<26}{direct:>5}")
    print(f"  {GREEN}✓{RESET} {'Group member rows':<26}{len(rows) - direct:>5}")
    fail_color = RED if _error_count else DIM
    label = "Couldn't read"
    print(f"  {fail_color}✗{RESET} {label:<26}{_error_count:>5}")
    print(f"  {DIM}Took {took:.1f}s{RESET}")

    heading("Output")
    print(f"  {os.path.relpath(OUTPUT_PATH)}")
    note = f"{_error_count} error(s)" if _error_count else "no errors"
    print(f"  {fail_color}{os.path.relpath(_errors_path)}  {note}{RESET}")
    if _error_count:
        print(f"\n  {YELLOW}Some vaults or groups couldn't be read, so the CSV is missing their access.{RESET}")
    print()
    sys.exit(1 if _error_count else 0)


if __name__ == "__main__":
    main()
