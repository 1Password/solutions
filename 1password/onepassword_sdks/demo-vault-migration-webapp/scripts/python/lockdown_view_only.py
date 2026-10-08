#!/usr/bin/env python3
"""Brings every user and group on your vaults down to view only.

Checks every vault you can manage. Anyone assigned directly, and any group
assigned, ends up with allow_viewing and nothing else. allow_viewing is granted
first, then everything else is revoked, so nobody loses access in between.

Left alone on purpose: the Recovery, Administrators, Owners, Provision Managers
and Security groups, since changing them would get in the way of running the
account, and the Employee vault.

It's safe to run more than once. Current permissions are checked first, and
anyone already view only is left as is. Work runs 5 at a time and each op
command gets up to 5 tries.

Every change, retry and failure goes in logs/<timestamp>/errors.log, and
failures also go in failed_changes.jsonl.

Options:
  --account  The 1Password account to sign in to, only used if the CLI isn't
             already signed in. Falls back to the OP_ACCOUNT environment
             variable, then asks.
  --dry-run  Show what would change without granting or revoking anything.

Examples:
  python3 lockdown_view_only.py --dry-run
  python3 lockdown_view_only.py --account mycompany

Written for 1Password Teams, which has three permission levels: allow_viewing,
allow_editing and allow_managing.
Requires Python 3.9 or later and the 1Password CLI.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
THREADS = 5
MAX_ATTEMPTS = 5
OP_TIMEOUT_SECONDS = 30
TARGET_PERMISSION = "allow_viewing"
IGNORED_VAULT_NAME = "employee"
IGNORED_GROUP_NAMES = {"recovery", "administrators", "owners", "provision managers", "security"}

PERMANENT_ERRORS = [
    "does not have access",
    "not found",
    "isn't a vault",
    "isn't a group",
    "isn't a user",
    "isn't a member",
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
_logs_dir = SCRIPT_DIR / "logs" / _run_started.strftime("%Y-%m-%d_%H-%M-%S")
_failed_path = _logs_dir / "failed_changes.jsonl"
_errors_log_path = _logs_dir / "errors.log"
_log_lock = threading.Lock()
_progress = {"label": "", "done": 0, "total": 0}
_account: Optional[str] = None


# Draws the progress bar on the current line, only when running in a terminal
def draw_progress() -> None:
    if not IS_TTY or not _progress["total"]:
        return
    done, total = _progress["done"], _progress["total"]
    width = 24
    filled = int(width * done / total)
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r  {_progress['label']:<22} {CYAN}{bar}{RESET} {done}/{total}\033[K")
    sys.stdout.flush()


# Starts a new progress bar
def start_progress(label: str, total: int) -> None:
    _progress.update(label=label, done=0, total=total)
    draw_progress()


# Moves the progress bar forward by one
def step_progress() -> None:
    with _log_lock:
        _progress["done"] += 1
        draw_progress()


# Clears the progress bar, and leaves a finished line in its place if there's one to show
def end_progress(result: str = "") -> None:
    if IS_TTY and _progress["total"]:
        sys.stdout.write("\r\033[K")
    if result:
        print(f"  {_progress['label']:<22} {result}")
    _progress["total"] = 0


# Prints above the progress bar so the two don't get mixed up
def say(text: str) -> None:
    with _log_lock:
        if IS_TTY and _progress["total"]:
            sys.stdout.write("\r\033[K")
        print(text)
        draw_progress()


# Prints a section heading
def heading(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# Prints an error and stops the script
def stop(message: str) -> None:
    print(f"{RED}{message}{RESET}", file=sys.stderr)
    sys.exit(1)


# Adds a timestamped line to errors.log, which keeps every change, retry and failure from the run
def write_log(message: str) -> None:
    with _log_lock:
        with _errors_log_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')}  {message}\n")


# Records a change that failed, on screen and in both log files
def record_failure(vault: str, target_type: str, target: str, reason: str) -> None:
    write_log(f"failed: {vault} / {target_type}:{target}: {reason}")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vault": vault,
        "target_type": target_type,
        "target": target,
        "reason": reason,
    }
    with _log_lock:
        with _failed_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    say(f"  {RED}✗ {BOLD}{vault}{RESET}  {DIM}{target_type}: {target}{RESET}\n      {RED}{reason}{RESET}")


# Runs an op command once, returning whether it worked, its output and a tidied up error
def run_op_once(args: list, timeout: int = OP_TIMEOUT_SECONDS) -> tuple:
    cmd = ["op"] + args + (["--account", _account] if _account else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "", f"timed out after {timeout}s"
    except Exception as exc:
        return False, "", str(exc)
    if r.returncode == 0:
        return True, r.stdout, ""
    return False, "", re.sub(r"^\[ERROR\]\s*(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\s*)?", "", r.stderr.strip())


# Runs an op command with up to MAX_ATTEMPTS tries, unless the error won't go away
def run_op(args: list, what: str) -> tuple:
    err = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ok, stdout, err = run_op_once(args)
        if ok:
            return True, stdout, ""
        if attempt == MAX_ATTEMPTS or any(p in err.lower() for p in PERMANENT_ERRORS):
            break
        write_log(f"retrying {what} (attempt {attempt}/{MAX_ATTEMPTS}): {err}")
        time.sleep(2 ** attempt)
    return False, "", err


# Turns op's JSON output into a list, treating empty output as an empty list
def parse_json(text: str) -> list:
    return json.loads(text) if text and text.strip() else []


# Reuses the CLI's session if it's signed in, otherwise signs in and passes --account from then on
def connect_account(account_arg: Optional[str]) -> dict:
    global _account
    ok, stdout, _ = run_op_once(["whoami", "--format=json"], timeout=15)
    if ok:
        return json.loads(stdout)

    account = account_arg or os.environ.get("OP_ACCOUNT", "").strip()
    if not account:
        account = input("1Password account (sign-in address or shorthand): ").strip()
    print(f"Not signed in, running op signin for {account}...")
    if subprocess.run(["op", "signin", "--account", account]).returncode != 0:
        stop("op signin failed.")
    _account = account
    ok, stdout, err = run_op(["whoami", "--format=json"], "whoami")
    if not ok:
        stop(f"Still not signed in: {err}")
    return json.loads(stdout)


# Shows who we're running as
def show_header(me: dict, mode: str) -> None:
    title = "Lock down vaults to view only"
    line = "─" * (len(title) + 4)
    print(f"\n{CYAN}╭{line}╮{RESET}\n{CYAN}│{RESET}  {BOLD}{title}{RESET}  {CYAN}│{RESET}\n{CYAN}╰{line}╯{RESET}")
    print(f"  {DIM}{'Account':<11}{RESET}{me.get('url', '?').replace('https://', '').rstrip('/')}")
    print(f"  {DIM}{'Signed in':<11}{RESET}{me.get('email', '?')}")
    print(f"  {DIM}{'Mode':<11}{RESET}{GREEN if mode == 'Live' else YELLOW}{mode}{RESET}")


# Lists the vaults we can manage, trying manage_vault first and allow_managing for Teams accounts
def get_manageable_vaults() -> list:
    ok, stdout, err = run_op_once(["vault", "list", "--permission=manage_vault", "--format=json"])
    if not ok:
        write_log(f"manage_vault didn't work as a vault list filter ({err}), trying allow_managing instead")
        first = err
        ok, stdout, err = run_op_once(["vault", "list", "--permission=allow_managing", "--format=json"])
        if not ok:
            stop(f"Couldn't list the vaults you manage.\n  manage_vault: {first}\n  allow_managing: {err}")
    return [v for v in parse_json(stdout) if v.get("name", "").strip().lower() != IGNORED_VAULT_NAME]


# Lists the users and groups on one vault
def fetch_vault(vault: dict) -> dict:
    users = run_op(["vault", "user", "list", vault["id"], "--format=json"], f"list users on vault {vault['id']}")
    groups = run_op(["vault", "group", "list", vault["id"], "--format=json"], f"list groups on vault {vault['id']}")
    return {"vault": vault, "users": users, "groups": groups}


# Reads who's on every vault, users and groups, skipping the groups we leave alone
def read_assignments(vaults: list) -> tuple:
    entries = []
    failed = 0
    start_progress("Reading vaults", len(vaults))
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for future in as_completed([pool.submit(fetch_vault, v) for v in vaults]):
            result = future.result()
            step_progress()
            vault = result["vault"]
            ok, stdout, err = result["users"]
            if ok:
                for u in parse_json(stdout):
                    entries.append({"vault_id": vault["id"], "vault_name": vault["name"], "target_type": "user",
                                    "target_id": u["id"], "target_label": u.get("email") or u["id"],
                                    "permissions": u.get("permissions", [])})
            else:
                record_failure(vault["name"], "user", "(listing users)", err)
                failed += 1
            ok, stdout, err = result["groups"]
            if ok:
                for g in parse_json(stdout):
                    if g.get("name", "").strip().lower() in IGNORED_GROUP_NAMES:
                        continue
                    entries.append({"vault_id": vault["id"], "vault_name": vault["name"], "target_type": "group",
                                    "target_id": g["id"], "target_label": g.get("name") or g["id"],
                                    "permissions": g.get("permissions", [])})
            else:
                record_failure(vault["name"], "group", "(listing groups)", err)
                failed += 1
    end_progress(f"{len(entries)} user/group assignment(s)")
    return entries, failed


# Grants allow_viewing first so nobody loses access for a moment, then revokes everything else
def apply_change(entry: dict, dry_run: bool) -> tuple:
    current = set(entry["permissions"])
    to_revoke = sorted(p for p in current if p and p != TARGET_PERMISSION)
    to_grant = [] if TARGET_PERMISSION in current else [TARGET_PERMISSION]
    if not to_grant and not to_revoke:
        return entry, to_grant, to_revoke, False, ""
    if dry_run:
        return entry, to_grant, to_revoke, True, ""

    kind = entry["target_type"]
    for action, perms in (("grant", to_grant), ("revoke", to_revoke)):
        if not perms:
            continue
        ok, _, err = run_op(["vault", kind, action, "--vault", entry["vault_id"], f"--{kind}", entry["target_id"],
                             "--permissions", ",".join(perms)],
                            f"{action} on {kind} {entry['target_id']} in {entry['vault_name']}")
        if not ok:
            return entry, to_grant, to_revoke, True, err
    return entry, to_grant, to_revoke, True, ""


# Brings everyone who isn't view only down to view only, 5 at a time, and returns the counts
def set_view_only(entries: list, dry_run: bool) -> dict:
    results = {"changed": 0, "unchanged": 0, "failed": 0}
    start_progress("Updating", len(entries))
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for future in as_completed([pool.submit(apply_change, e, dry_run) for e in entries]):
            e, to_grant, to_revoke, changed, err = future.result()
            step_progress()
            if err:
                record_failure(e["vault_name"], e["target_type"], e["target_label"], err)
                results["failed"] += 1
                continue
            if not changed:
                results["unchanged"] += 1
                continue
            results["changed"] += 1
            mark = f"{YELLOW}•{RESET}" if dry_run else f"{GREEN}✓{RESET}"
            lines = [f"  {mark} {BOLD}{e['vault_name']}{RESET}  {DIM}{e['target_type']}: {e['target_label']}{RESET}"]
            if to_grant:
                lines.append(f"      {GREEN}{'would add' if dry_run else 'added':<13}{RESET}{', '.join(to_grant)}")
            if to_revoke:
                lines.append(f"      {YELLOW}{'would remove' if dry_run else 'removed':<13}{RESET}{', '.join(to_revoke)}")
            say("\n".join(lines))
            target = f"{e['target_type']}:{e['target_label']}"
            if dry_run:
                parts = (["grant allow_viewing"] if to_grant else []) + ([f"revoke {','.join(to_revoke)}"] if to_revoke else [])
                write_log(f"DRY-RUN: {e['vault_name']} -> {target}: {' and '.join(parts)}")
            else:
                write_log(f"locked down {e['vault_name']} -> {target} to view only")
    end_progress()
    if not results["changed"] and not results["failed"]:
        print(f"  {DIM}Everyone's already view only{RESET}")
    return results


# Reads the options and runs the whole thing
def main() -> None:
    ap = argparse.ArgumentParser(description="Lock down vault access to view only, leaving the admin groups untouched.")
    ap.add_argument("--account", help="1Password account shorthand, only used if the CLI isn't signed in")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change without granting or revoking anything")
    args = ap.parse_args()

    _logs_dir.mkdir(parents=True, exist_ok=True)
    me = connect_account(args.account)
    mode = "Dry run" if args.dry_run else "Live"
    show_header(me, mode)
    write_log(f"Lock down vaults to view only, {mode}, signed in as {me.get('email', '?')} on {me.get('url', '?')}")

    heading("Checking")
    vaults = get_manageable_vaults()
    print(f"  {'Vaults found':<22} {len(vaults)} {DIM}(Employee vault excluded){RESET}")
    entries, read_failed = read_assignments(vaults)

    heading("Would change" if args.dry_run else "Changes")
    results = set_view_only(entries, args.dry_run)
    failed = results["failed"] + read_failed
    took = (datetime.now() - _run_started).total_seconds()

    heading("Summary")
    print(f"  {GREEN}✓{RESET} {'Would change' if args.dry_run else 'Changed':<26}{results['changed']:>5}")
    print(f"  {DIM}·{RESET} {'Already view only':<26}{results['unchanged']:>5}")
    print(f"  {RED if failed else DIM}✗{RESET} {'Failed':<26}{failed:>5}")
    print(f"  {DIM}Took {took:.1f}s{RESET}")
    verb = "would be changed" if args.dry_run else "changed"
    write_log(f"Done. {results['changed']} {verb}, {results['unchanged']} already view-only, {failed} failed.")

    heading("Logs")
    print(f"  {os.path.relpath(_logs_dir)}/")
    print(f"    {'errors.log':<24}{DIM}every change, retry and failure{RESET}")
    if _failed_path.exists():
        print(f"    {'failed_changes.jsonl':<24}{RED}{failed} failure(s){RESET}")
    print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
