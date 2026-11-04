#!/usr/bin/env python3
"""Brings every user and group on your vaults down to view only.

Checks every vault you can manage, or only the vaults in a CSV with --file.
Anyone assigned directly, and any group assigned, ends up with view access and
nothing else. Which permission that is depends on the account, and the script
checks the account type before changing anything:

  Business  view_items. They can see the items, but can't reveal or copy
            passwords, see item history, or change anything.
  Teams     allow_viewing, since Teams only has allow_viewing, allow_editing
            and allow_managing. They can see the items and can reveal and copy
            passwords, but can't change anything or manage the vault.

Everything else is revoked first, then the view permission is granted. The view
permission itself is never revoked, so anyone who already has it keeps access
throughout. Anyone who didn't have it is off the vault briefly between the two
steps, and a failed grant there is reported as a failure.

Left alone on purpose: the Recovery, Administrators, Owners, Provision Managers
and Security groups, since changing them would get in the way of running the
account, and the Employee vault.

It's safe to run more than once. Current permissions are checked first, and
anyone already view only is left as is. Work runs 5 at a time and each op
command gets up to 5 tries.

Every change, retry and failure goes in logs/<timestamp>/errors.log, and
failures also go in failed_changes.jsonl.

Options:
  --file     A CSV of the vaults to lock down. Leave it out to lock down every
             vault you can manage. It needs a vaultName or vaultUUID column
             (name, vault, id and uuid work too, in any case), and if there's
             an include column, only rows set to yes are used. Rows
             that don't match a vault you can manage are listed and skipped.
             If the CSV also lists who was assigned (an email column, plus
             assignment and groupName, as in vault_access_report.csv), anyone
             listed who's no longer on the vault is added back with the view
             permission: users assigned directly as users, and groups as
             groups. The groups this script leaves alone are skipped here too.
  --account  The 1Password account to sign in to, only used if the CLI isn't
             already signed in. Falls back to the OP_ACCOUNT environment
             variable, then asks.
  --dry-run  Show what would change without granting or revoking anything.

Examples:
  python3 lockdown_view_only.py --dry-run
  python3 lockdown_view_only.py --file vaults.csv --dry-run
  python3 lockdown_view_only.py --account mycompany

Works on 1Password Business and Teams. The account type comes from op account
get, and if that doesn't say, from whether the vault list works with
manage_vault (Business) or only allow_managing (Teams).
Requires Python 3.9 or later and the 1Password CLI.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
THREADS = 5
MAX_ATTEMPTS = 5
OP_TIMEOUT_SECONDS = 30
# What everyone ends up with, by account type
VIEW_PERMISSIONS = {"Business": "view_items", "Teams": "allow_viewing"}
# Business accounts can report a whole level instead of the permissions in it, so levels are
# expanded there and revoking "everything else" never takes view_items away with a level. Teams
# only has the levels, so any granular names are folded back into their level instead.
PERMISSION_LEVELS = {
    "allow_viewing": ["view_items", "view_and_copy_passwords", "view_item_history"],
    "allow_editing": ["create_items", "edit_items", "archive_items", "delete_items", "import_items",
                      "export_items", "copy_and_share_items", "print_items"],
    "allow_managing": ["manage_vault"],
}
IGNORED_VAULT_NAME = "employee"
IGNORED_GROUP_NAMES = {"recovery", "administrators", "owners", "provision managers", "security"}
YES_VALUES = {"yes", "y", "true", "1", "x"}
COLUMN_NAMES = {
    "include": {"include"},
    "vaultName": {"vaultname", "name", "vault"},
    "vaultUUID": {"vaultuuid", "vaultid", "uuid", "id"},
    "email": {"email", "useremail"},
    "assignment": {"assignment"},
    "groupName": {"groupname"},
}

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
_listed_with = "manage_vault"


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
    return (json.loads(text) or []) if text and text.strip() else []   # op prints null for an empty list


# Manual sign-in prints the session instead of saving it, so this saves it for the op commands we run
def keep_session(signin_output: str) -> None:
    for name, value in re.findall(r"(OP_SESSION_\w+)\s*=\s*[\"']?([^\"'\s]+)", signin_output):
        os.environ[name] = value


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
    result = subprocess.run(["op", "signin", "--account", account], stdout=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stop("op signin failed.")
    keep_session(result.stdout)
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
    global _listed_with
    ok, stdout, err = run_op_once(["vault", "list", "--permission=manage_vault", "--format=json"])
    if not ok:
        write_log(f"manage_vault didn't work as a vault list filter ({err}), trying allow_managing instead")
        first = err
        ok, stdout, err = run_op_once(["vault", "list", "--permission=allow_managing", "--format=json"])
        if not ok:
            stop(f"Couldn't list the vaults you manage.\n  manage_vault: {first}\n  allow_managing: {err}")
        _listed_with = "allow_managing"
    return [v for v in parse_json(stdout) if v.get("name", "").strip().lower() != IGNORED_VAULT_NAME]


# Works out whether this is a Business or Teams account: op account get first, then falls back to
# which permission the vault list worked with. Returns the type and where it came from.
def get_account_type() -> tuple:
    ok, stdout, err = run_op(["account", "get", "--format=json"], "account get")
    kind = ""
    if ok:
        try:
            kind = str(json.loads(stdout).get("type") or "").upper()
        except (ValueError, AttributeError):
            kind = ""
    if kind == "BUSINESS":
        return "Business", "op account get"
    if kind in ("TEAM", "TEAMS"):
        return "Teams", "op account get"
    write_log(f"op account get didn't say Business or Teams ({f'type {kind!r}' if ok else err}), going by the vault list instead")
    if _listed_with == "allow_managing":
        return "Teams", "vault list needed allow_managing"
    return "Business", "vault list worked with manage_vault"


def normalize_header(header: str) -> str:
    return re.sub(r"[\s_-]", "", (header or "").lower())


# Works out which CSV column is which, ignoring case, spaces and underscores
def find_columns(fieldnames: list) -> dict:
    found = {}
    for header in fieldnames:
        key = normalize_header(header)
        for column, names in COLUMN_NAMES.items():
            if key in names and column not in found:
                found[column] = header
    return found


# Reads the CSV and returns the rows to use, which is every row unless there's an include column
def read_vault_csv(path: Path) -> dict:
    if not path.exists():
        stop(f"Can't find {path}. Point --file at your CSV of vaults.")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = find_columns(reader.fieldnames or [])
        if "vaultName" not in columns and "vaultUUID" not in columns:
            stop(f"{path.name} needs a vaultName or vaultUUID column (name, vault, id or uuid work too).\n"
                 f"Found: {', '.join(reader.fieldnames or []) or 'no header row'}")
        rows = [{c: (row.get(columns[c]) or "").strip() if c in columns else "" for c in COLUMN_NAMES}
                for row in reader]
    has_include = "include" in columns
    picked = [r for r in rows if (r["vaultUUID"] or r["vaultName"])
              and (not has_include or r["include"].lower() in YES_VALUES)]
    return {"picked": picked, "total": len(rows), "has_include": has_include,
            "has_assignments": "email" in columns and "assignment" in columns}


# Matches each picked row to a live vault by ID, or by name when the ID is blank
def match_rows(rows: list, vaults: list) -> tuple:
    by_id = {v["id"]: v for v in vaults}
    by_name = {}
    for v in vaults:
        by_name.setdefault(v["name"].lower(), []).append(v)
    matched, issues, seen = {}, [], set()
    for r in rows:
        key = (r["vaultUUID"], r["vaultName"].lower())
        if key in seen:
            continue
        seen.add(key)
        label = r["vaultName"] or r["vaultUUID"]
        if r["vaultUUID"]:
            if r["vaultUUID"] in by_id:
                matched[r["vaultUUID"]] = by_id[r["vaultUUID"]]
            else:
                issues.append((label, f"no vault with ID {r['vaultUUID']}"))
            continue
        found = by_name.get(r["vaultName"].lower(), [])
        if len(found) == 1:
            matched[found[0]["id"]] = found[0]
        elif len(found) > 1:
            issues.append((label, f"{len(found)} vaults have this name, add the vaultUUID"))
        else:
            issues.append((label, "no vault with this name"))
    return sorted(matched.values(), key=lambda v: v["name"].lower()), issues


# Lists the users and groups the CSV says were on each vault, as (vault, "user" or "group", email or name)
def csv_assignments(rows: list, vaults: list) -> list:
    by_id = {v["id"]: v for v in vaults}
    by_name = {}
    for v in vaults:
        key = v["name"].lower()
        by_name[key] = None if key in by_name else v   # None when the name isn't unique
    wanted = {}
    for r in rows:
        vault = by_id.get(r["vaultUUID"]) if r["vaultUUID"] else by_name.get(r["vaultName"].lower())
        assignment = r["assignment"].strip()
        if not vault or not assignment:
            continue
        if assignment == "Direct":
            if r["email"]:
                wanted[(vault["id"], "user", r["email"].lower())] = (vault, "user", r["email"].lower())
            continue
        m = re.match(r"^Group \((.*)\)$", assignment)
        group = r["groupName"] or (m.group(1) if m else "")
        if not group or group.lower() in IGNORED_GROUP_NAMES:
            continue
        wanted[(vault["id"], "group", group.lower())] = (vault, "group", group.lower())
    return list(wanted.values())


# Adds an entry with no permissions for everyone the CSV lists who isn't on the vault now, so they're granted the view permission
def add_missing_assignments(wanted: list, entries: list) -> tuple:
    added, not_found = 0, []
    if not wanted:
        return added, not_found
    ok_u, users, err_u = run_op(["user", "list", "--format=json"], "list users")
    ok_g, groups, err_g = run_op(["group", "list", "--format=json"], "list groups")
    if not ok_u or not ok_g:
        stop(f"Couldn't list users and groups: {err_u}{err_g}")
    index = {"user": {u["email"].strip().lower(): u for u in parse_json(users) if u.get("email")},
             "group": {g["name"].strip().lower(): g for g in parse_json(groups) if g.get("name")}}
    present = {(e["vault_id"], e["target_id"]) for e in entries}
    for vault, kind, key in wanted:
        target = index[kind].get(key)
        if not target:
            not_found.append(f"{vault['name']} / {kind}: {key}")
            write_log(f"not found, can't add back: {vault['name']} / {kind}:{key}")
            continue
        if (vault["id"], target["id"]) in present:
            continue
        present.add((vault["id"], target["id"]))
        entries.append({"vault_id": vault["id"], "vault_name": vault["name"], "target_type": kind,
                        "target_id": target["id"], "target_label": target.get("email" if kind == "user" else "name") or key,
                        "permissions": [], "added_back": True})
        added += 1
    return added, not_found


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


# Puts permissions in the account's terms: individual permissions for Business, levels for Teams
def normalize_permissions(permissions: list, account_type: str) -> set:
    current = set()
    for p in filter(None, permissions):
        if account_type == "Teams":
            current.add(next((level for level, parts in PERMISSION_LEVELS.items() if p in parts), p))
        else:
            current.update(PERMISSION_LEVELS.get(p, [p]))
    return current


# Revokes everything but the view permission first, then grants it to anyone who didn't have it
def apply_change(entry: dict, target: str, account_type: str, dry_run: bool) -> tuple:
    current = normalize_permissions(entry["permissions"], account_type)
    to_revoke = sorted(p for p in current if p != target)
    to_grant = [] if target in current else [target]
    if not to_grant and not to_revoke:
        return entry, to_grant, to_revoke, False, ""
    if dry_run:
        return entry, to_grant, to_revoke, True, ""

    kind = entry["target_type"]
    for action, perms in (("revoke", to_revoke), ("grant", to_grant)):
        if not perms:
            continue
        ok, _, err = run_op(["vault", kind, action, "--vault", entry["vault_id"], f"--{kind}", entry["target_id"],
                             "--permissions", ",".join(perms)],
                            f"{action} on {kind} {entry['target_id']} in {entry['vault_name']}")
        if not ok:
            return entry, to_grant, to_revoke, True, err
    return entry, to_grant, to_revoke, True, ""


# Brings everyone who isn't view only down to view only, 5 at a time, and returns the counts
def set_view_only(entries: list, target: str, account_type: str, dry_run: bool) -> dict:
    results = {"changed": 0, "unchanged": 0, "failed": 0}
    start_progress("Updating", len(entries))
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for future in as_completed([pool.submit(apply_change, e, target, account_type, dry_run) for e in entries]):
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
            back = f"  {YELLOW}(added back from the CSV){RESET}" if e.get("added_back") else ""
            lines = [f"  {mark} {BOLD}{e['vault_name']}{RESET}  {DIM}{e['target_type']}: {e['target_label']}{RESET}{back}"]
            if to_grant:
                lines.append(f"      {GREEN}{'would add' if dry_run else 'added':<13}{RESET}{', '.join(to_grant)}")
            if to_revoke:
                lines.append(f"      {YELLOW}{'would remove' if dry_run else 'removed':<13}{RESET}{', '.join(to_revoke)}")
            say("\n".join(lines))
            who = f"{e['target_type']}:{e['target_label']}"
            if dry_run:
                parts = ([f"grant {target}"] if to_grant else []) + ([f"revoke {','.join(to_revoke)}"] if to_revoke else [])
                write_log(f"DRY-RUN: {e['vault_name']} -> {who}: {' and '.join(parts)}")
            else:
                write_log(f"locked down {e['vault_name']} -> {who} to {target} only")
    end_progress()
    if not results["changed"] and not results["failed"]:
        print(f"  {DIM}Everyone already has {target} only{RESET}")
    return results


# Reads the options and runs the whole thing
def main() -> None:
    ap = argparse.ArgumentParser(description="Lock down vault access to view only, leaving the admin groups untouched.")
    ap.add_argument("--file", type=Path, help="CSV of the vaults to lock down, instead of every vault you can manage")
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
    account_type, source = get_account_type()
    target = VIEW_PERMISSIONS[account_type]
    print(f"  {'Account type':<22} {account_type} {DIM}(locking down to {target}){RESET}")
    write_log(f"Account type {account_type} (from {source}), locking down to {target}")
    sheet = None
    if args.file:
        sheet = read_vault_csv(args.file)
        vaults, issues = match_rows(sheet["picked"], vaults)
        picked = f"{len(sheet['picked'])} set to include" if sheet["has_include"] else f"{len(sheet['picked'])} with a vault"
        print(f"  {'From CSV':<22} {len(vaults)} matched {DIM}({sheet['total']} rows, {picked}){RESET}")
        write_log(f"Read {sheet['total']} rows from {args.file}, {len(sheet['picked'])} picked, {len(vaults)} matched")
        for label, reason in issues:
            write_log(f"not matched: {label}: {reason}")
            print(f"  {YELLOW}!{RESET} {label}  {DIM}{reason}, skipped{RESET}")
        if not vaults:
            stop(f"None of the vaults in {args.file.name} matched a vault you can manage.")
    entries, read_failed = read_assignments(vaults)
    if sheet and sheet["has_assignments"]:
        added, not_found = add_missing_assignments(csv_assignments(sheet["picked"], vaults), entries)
        print(f"  {'Not on vault any more':<22} {added} in the CSV {DIM}(will be added back with {target}){RESET}")
        if not_found:
            print(f"  {'Not in this account':<22} {YELLOW}{len(not_found)}, listed in errors.log{RESET}")

    heading("Would change" if args.dry_run else "Changes")
    results = set_view_only(entries, target, account_type, args.dry_run)
    failed = results["failed"] + read_failed
    took = (datetime.now() - _run_started).total_seconds()

    heading("Summary")
    print(f"  {GREEN}✓{RESET} {'Would change' if args.dry_run else 'Changed':<26}{results['changed']:>5}")
    print(f"  {DIM}·{RESET} {f'Already {target} only':<26}{results['unchanged']:>5}")
    print(f"  {RED if failed else DIM}✗{RESET} {'Failed':<26}{failed:>5}")
    print(f"  {DIM}Took {took:.1f}s{RESET}")
    verb = "would be changed" if args.dry_run else "changed"
    write_log(f"Done. {results['changed']} {verb}, {results['unchanged']} already {target} only, {failed} failed.")

    heading("Logs")
    print(f"  {os.path.relpath(_logs_dir)}/")
    print(f"    {'errors.log':<24}{DIM}every change, retry and failure{RESET}")
    if _failed_path.exists():
        print(f"    {'failed_changes.jsonl':<24}{RED}{failed} failure(s){RESET}")
    print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
