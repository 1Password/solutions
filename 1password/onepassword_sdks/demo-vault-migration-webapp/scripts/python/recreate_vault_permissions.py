#!/usr/bin/env python3
"""Recreates vault access from the CSV made by shared_vaults_permissions_mapping.py.

Reads vault_access_report.csv and grants the same users and groups the same
permissions on the matching vaults in the account you're signed in to. Use it
after migrating vaults to a new account.

Matching is by name, never by ID: vaults by name, groups by name and users by
email. A "(Migrated)" on the end of a vault name is ignored, so Finance matches
Finance (Migrated). If both exist, the (Migrated) one is used.

Groups that don't exist can be created, along with their members, with
--create-groups. Recovery, Team Members, Administrators, Provision Managers,
Security and Owners are never created. The Recovery group's access is always
skipped since 1Password manages it.

Permissions are only added, never removed. Work runs 10 at a time and each op
command is retried up to 3 times.

Everything that couldn't be done (missing vaults, users or groups, and failures)
is summed up on screen and listed in full in
logs/recreate_<timestamp>/not_recreated.csv. Every change is written to
audit.log in the same folder.

Options:
  --file              The CSV to read. Defaults to vault_access_report.csv next
                      to this script.
  --account           The 1Password account to use (sign-in address or
                      shorthand), if you're signed in to more than one.
  --create-groups     Create missing groups and add their members without asking.
  --no-create-groups  Never create groups, and don't ask. Without either option,
                      you're asked when groups are missing.
  --dry-run           Show what would happen without changing anything.

Examples:
  python3 recreate_vault_permissions.py --dry-run
  python3 recreate_vault_permissions.py --file ./access.csv --create-groups

Requires Python 3.9 or later and the 1Password CLI, signed in as someone who can
manage the vaults, groups and users involved.
A group with no members has no rows in the CSV, so its vault access can't be
recreated.
"""
import argparse
import ast
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
DEFAULT_CSV = SCRIPT_DIR / "vault_access_report.csv"
THREADS = 10
MAX_RETRIES = 3
OP_TIMEOUT_SECONDS = 30
NAMES_SHOWN = 3

MIGRATED_SUFFIX = "(Migrated)"
BUILT_IN_GROUPS = {"recovery", "team members", "administrators", "provision managers", "security", "owners"}
SKIPPED_GROUPS = {"recovery"}
REQUIRED_COLUMNS = {"vaultName", "userName", "groupName", "email", "assignment", "permissions"}

PERMANENT_ERRORS = [
    "does not have access",
    "not found",
    "isn't a vault",
    "isn't a group",
    "isn't a user",
    "not authorized",
    "no accounts for filter",
    "already exists",
]

IS_TTY = sys.stdout.isatty()
USE_COLOR = IS_TTY and not os.environ.get("NO_COLOR")
BOLD, DIM, RED, GREEN, YELLOW, CYAN, RESET = (
    ("\033[1m", "\033[2m", "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[0m")
    if USE_COLOR else ("",) * 7
)

_run_started = datetime.now()
_logs_dir = SCRIPT_DIR / "logs" / f"recreate_{_run_started.strftime('%Y-%m-%d_%H-%M-%S')}"
_audit_path = _logs_dir / "audit.log"
_report_path = _logs_dir / "not_recreated.csv"
_log_lock = threading.Lock()
_progress = {"label": "", "done": 0, "total": 0}


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


# Clears the progress bar and leaves a finished line in its place
def end_progress(result: str) -> None:
    if IS_TTY and _progress["total"]:
        sys.stdout.write("\r\033[K")
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


# Prints a label and value lined up with the rest of the section
def field(label: str, value) -> None:
    print(f"  {label:<22} {value}")


# Writes a timestamped entry to the audit log
def audit(status: str, subject: str, *details: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    lines = [f"{stamp}  {status:<12} {subject}"] + [f"{'':<24}{d}" for d in details]
    with _log_lock:
        with _audit_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# Adds --account to a command when one was given
def op_args(base: list, account: Optional[str]) -> list:
    return base + (["--account", account] if account else [])


# Runs an op command, retrying up to MAX_RETRIES times unless the error won't go away
def run_op(cmd: list, what: str) -> tuple:
    err = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=OP_TIMEOUT_SECONDS)
            if r.returncode == 0:
                return True, r.stdout, ""
            err = re.sub(r"^\[ERROR\]\s*(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\s*)?", "", r.stderr.strip())
        except Exception as exc:
            err = str(exc)
        if attempt == MAX_RETRIES or any(p in err.lower() for p in PERMANENT_ERRORS):
            break
        if _audit_path.exists():
            audit(f"RETRY {attempt + 1}/{MAX_RETRIES}", what, err)
        time.sleep(2 ** attempt)
    return False, "", err


# Runs an op command that has to work, and stops the script if it doesn't
def must_op(cmd: list, what: str) -> list:
    ok, stdout, err = run_op(cmd, what)
    if not ok:
        print(f"\n{RED}Couldn't {what}: {err}{RESET}", file=sys.stderr)
        sys.exit(1)
    return json.loads(stdout or "[]")


# Turns the permissions column, written as a Python list, back into a list
def parse_permissions(text: str) -> list:
    text = (text or "").strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        value = text.strip("[]").replace("'", "").replace('"', "").split(",")
    if isinstance(value, str):
        value = [value]
    return sorted({p.strip() for p in value if p and p.strip()})


# Drops "(Migrated)" from the end of a vault name so source and destination names line up
def base_name(name: str) -> str:
    name = name.strip()
    if name.lower().endswith(MIGRATED_SUFFIX.lower()):
        name = name[: -len(MIGRATED_SUFFIX)]
    return name.strip().lower()


# Reads the mapping CSV into vault assignments and group memberships, ignoring every UUID in it
def load_csv(path: Path) -> tuple:
    if not path.exists():
        print(f"{RED}Can't find {path}. Point to it with --file.{RESET}", file=sys.stderr)
        sys.exit(1)
    vaults, members, rows = {}, {}, 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            print(f"{RED}{path.name} is missing columns: {', '.join(sorted(missing))}{RESET}", file=sys.stderr)
            sys.exit(1)
        for row in reader:
            rows += 1
            vault_name = row["vaultName"].strip()
            email = row["email"].strip().lower()
            perms = parse_permissions(row["permissions"])
            vault = vaults.setdefault(vault_name, {"users": {}, "groups": {}})
            if row["assignment"].strip() == "Direct":
                vault["users"][email] = perms
                continue
            group = (row["groupName"] or row["assignment"].strip()[len("Group ("):-1]).strip()
            vault["groups"][group] = perms
            if email:
                members.setdefault(group, set()).add(email)
    return vaults, members, rows


# Reads the vaults, users and groups that exist in the destination account
def load_destination(account: Optional[str]) -> tuple:
    start_progress("Reading destination", 3)
    vaults = must_op(op_args(["op", "vault", "list", "--permission", "manage_vault", "--format=json"], account),
                     "list vaults")
    step_progress()
    users = must_op(op_args(["op", "user", "list", "--format=json"], account), "list users")
    step_progress()
    groups = must_op(op_args(["op", "group", "list", "--format=json"], account), "list groups")
    step_progress()
    end_progress(f"{len(vaults)} vaults, {len(users)} users, {len(groups)} groups")

    vault_index = {}
    for v in vaults:
        vault_index.setdefault(base_name(v["name"]), []).append(v)
    user_index = {u["email"].strip().lower(): u for u in users if u.get("email")}
    group_index = {g["name"].strip().lower(): g for g in groups}
    return vault_index, user_index, group_index


# Builds one row for the report of things that couldn't be recreated
def make_issue(category: str, vault: str, kind: str, name: str, perms: list, reason: str) -> dict:
    return {"category": category, "vault": vault, "type": kind, "name": name,
            "permissions": ", ".join(perms), "reason": reason}


# Finds the destination vault for a source vault name, preferring the "(Migrated)" copy if there are both
def match_vault(name: str, vault_index: dict) -> tuple:
    candidates = vault_index.get(base_name(name), [])
    if len(candidates) > 1:
        migrated = [v for v in candidates if v["name"].strip().lower().endswith(MIGRATED_SUFFIX.lower())]
        candidates = migrated if migrated else candidates
    if not candidates:
        return None, "vault not found"
    if len(candidates) > 1:
        return None, f"{len(candidates)} vaults have this name"
    return candidates[0], ""


# Works out every grant to make, every group to create, and everything that can't be done
def plan(source: dict, members: dict, vault_index: dict, user_index: dict, group_index: dict,
         create_groups: bool) -> tuple:
    tasks, issues, to_create = [], [], set()

    for vault_name, assigned in sorted(source.items()):
        vault, reason = match_vault(vault_name, vault_index)
        if not vault:
            for email, perms in assigned["users"].items():
                issues.append(make_issue("vault", vault_name, "user", email, perms, reason))
            for group, perms in assigned["groups"].items():
                issues.append(make_issue("vault", vault_name, "group", group, perms, reason))
            continue

        for email, perms in assigned["users"].items():
            user = user_index.get(email)
            if not user:
                issues.append(make_issue("user", vault_name, "user", email, perms, "user not found"))
                continue
            tasks.append({"kind": "user", "vault": vault, "name": email, "id": user["id"], "perms": perms})

        for group, perms in assigned["groups"].items():
            key = group.lower()
            if key in SKIPPED_GROUPS:
                issues.append(make_issue("skipped", vault_name, "group", group, perms, "managed by 1Password, skipped"))
            elif key in group_index:
                tasks.append({"kind": "group", "vault": vault, "name": group,
                              "id": group_index[key]["id"], "perms": perms})
            elif key in BUILT_IN_GROUPS or not create_groups:
                issues.append(make_issue("group", vault_name, "group", group, perms, "group not found"))
            else:
                to_create.add(group)
                tasks.append({"kind": "group", "vault": vault, "name": group, "id": None, "perms": perms})

    for group in sorted(to_create):
        for email in sorted(members.get(group, ())):
            if email not in user_index:
                issues.append(make_issue("user", "", "group member", email, [], f"user not found, not added to {group}"))
    return tasks, issues, sorted(to_create)


# Lists the groups that are missing here but could be created
def creatable_groups(source: dict, group_index: dict) -> list:
    names = {g for v in source.values() for g in v["groups"]}
    return sorted(g for g in names if g.lower() not in group_index and g.lower() not in BUILT_IN_GROUPS)


# Asks whether to create missing groups, when --create-groups wasn't given and someone's at the keyboard
def ask_create_groups(missing: list) -> bool:
    if not missing or not sys.stdin.isatty():
        return False
    heading(f"{len(missing)} group(s) don't exist in this account")
    print(f"  {DIM}{shorten(missing, 8)}{RESET}")
    answer = input(f"  Create them and add their members? {DIM}[y/N]{RESET} ").strip().lower()
    return answer in ("y", "yes")


# Creates one group and adds the members it had in the source account
def create_group(group: str, emails: set, user_index: dict, account: Optional[str], dry_run: bool) -> tuple:
    found = [e for e in sorted(emails) if e in user_index]
    if dry_run:
        return group, "dry-run", len(found), len(emails), ""
    ok, stdout, err = run_op(op_args(["op", "group", "create", group, "--format=json"], account),
                             f"create group {group}")
    if not ok:
        return group, None, 0, len(emails), err
    group_id = json.loads(stdout)["id"]
    audit("CREATED", f"group {group}")
    added = 0
    for email in found:
        ok, _, err = run_op(op_args(["op", "group", "user", "grant", "--group", group_id,
                                     "--user", user_index[email]["id"]], account), f"add {email} to {group}")
        if ok:
            added += 1
            audit("ADDED", f"{email} to group {group}")
        else:
            audit("FAILED", f"add {email} to group {group}", err)
    return group, group_id, added, len(emails), ""


# Creates the missing groups on 10 threads and returns their new IDs
def create_all_groups(groups: list, members: dict, user_index: dict, account: Optional[str],
                      dry_run: bool, issues: list) -> dict:
    heading("Would create groups" if dry_run else "Creating groups")
    created = {}
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [pool.submit(create_group, g, members.get(g, set()), user_index, account, dry_run)
                   for g in groups]
        for future in as_completed(futures):
            group, group_id, added, total, err = future.result()
            if group_id:
                created[group] = group_id
                verb = "would add" if dry_run else "added"
                mark = f"{YELLOW}•{RESET}" if dry_run else f"{GREEN}✓{RESET}"
                say(f"  {mark} {BOLD}{group}{RESET}  {DIM}{verb} {added} of {total} member(s){RESET}")
            else:
                audit("FAILED", f"create group {group}", err)
                issues.append(make_issue("failed", "", "group", group, [], f"couldn't create group: {err}"))
                say(f"  {RED}✗{RESET} {BOLD}{group}{RESET}  {DIM}couldn't create it, see the report{RESET}")
    return created


# Grants one user or group its permissions on one vault
def grant(task: dict, account: Optional[str], dry_run: bool) -> str:
    if dry_run:
        return ""
    kind = task["kind"]
    cmd = op_args(["op", "vault", kind, "grant", "--vault", task["vault"]["id"], f"--{kind}", task["id"],
                   "--permissions", ",".join(task["perms"])], account)
    ok, _, err = run_op(cmd, f"grant {kind} {task['name']} on {task['vault']['name']}")
    return "" if ok else err


# Makes every grant on 10 threads, keeping failures for the report instead of printing them
def grant_all(tasks: list, account: Optional[str], dry_run: bool, issues: list) -> int:
    done = 0
    start_progress("Assignments", len(tasks))
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(grant, t, account, dry_run): t for t in tasks}
        for future in as_completed(futures):
            t = futures[future]
            err = future.result()
            step_progress()
            subject = f"{t['vault']['name']} / {t['kind']} {t['name']}"
            if err:
                audit("FAILED", subject, err)
                issues.append(make_issue("failed", t["vault"]["name"], t["kind"], t["name"], t["perms"], err))
            else:
                audit("WOULD GRANT" if dry_run else "GRANTED", subject, ", ".join(t["perms"]))
                done += 1
    end_progress(f"{done} of {len(tasks)} {'ready' if dry_run else 'done'}")
    return done


# Joins a few names for the screen and says how many more there are
def shorten(names: list, limit: int = NAMES_SHOWN) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f" +{len(names) - limit} more" if len(names) > limit else "")


# Writes the report of everything that couldn't be recreated
def write_report(issues: list) -> None:
    with _report_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["vault", "type", "name", "permissions", "reason"])
        writer.writeheader()
        for i in sorted(issues, key=lambda i: (i["category"], i["vault"].lower(), i["name"].lower())):
            writer.writerow({k: i[k] for k in writer.fieldnames})


# Shows what couldn't be done as one line per kind of problem, with the details left to the report
def show_issues(issues: list) -> None:
    if not issues:
        return
    heading("Couldn't recreate")
    rows = [
        ("vault", "Vaults not found", lambda i: i["vault"], YELLOW),
        ("user", "Users not found", lambda i: i["name"], YELLOW),
        ("group", "Groups not found", lambda i: i["name"], YELLOW),
        ("failed", "Failed", lambda i: f"{i['vault']} / {i['name']}" if i["vault"] else i["name"], RED),
        ("skipped", "Skipped (Recovery)", lambda i: i["vault"], DIM),
    ]
    for category, label, name_of, color in rows:
        matching = [i for i in issues if i["category"] == category]
        if not matching:
            continue
        names = sorted({name_of(i) for i in matching}, key=str.lower)
        print(f"  {color}{label:<22}{RESET}{len(names):>4}   {DIM}{shorten(names)}{RESET}")


# Prints the totals and where the logs went
def summary(granted: int, created: int, issues: list, dry_run: bool) -> int:
    failed = sum(1 for i in issues if i["category"] == "failed")
    not_possible = sum(1 for i in issues if i["category"] not in ("failed", "skipped"))
    took = (datetime.now() - _run_started).total_seconds()
    heading("Summary")
    print(f"  {GREEN}✓{RESET} {'Would assign' if dry_run else 'Assigned':<26}{granted:>5}")
    if created:
        print(f"  {GREEN}✓{RESET} {'Groups to create' if dry_run else 'Groups created':<26}{created:>5}")
    print(f"  {YELLOW if not_possible else DIM}!{RESET} {'Missing in this account':<26}{not_possible:>5}")
    print(f"  {RED if failed else DIM}✗{RESET} {'Failed':<26}{failed:>5}")
    print(f"  {DIM}Took {took:.1f}s{RESET}")
    with _audit_path.open("a", encoding="utf-8") as f:
        f.write(f"\nFinished   {granted} assigned, {created} group(s) created, {not_possible} missing, "
                f"{failed} failed, took {took:.1f}s\n")

    try:
        folder = _logs_dir.relative_to(Path.cwd())
    except ValueError:
        folder = _logs_dir
    heading("Logs")
    print(f"  {folder}/")
    print(f"    {_audit_path.name:<24}{DIM}every group created and permission granted{RESET}")
    if issues:
        print(f"    {_report_path.name:<24}{YELLOW}{len(issues)} assignment(s) that couldn't be recreated{RESET}")
    print()
    return 1 if failed else 0


# Shows who we're running as and stops if the CLI isn't signed in
def check_signed_in(account: Optional[str], csv_path: Path, mode: str) -> dict:
    ok, stdout, err = run_op(op_args(["op", "whoami", "--format=json"], account), "whoami")
    if not ok:
        print(f"{RED}Not signed in to 1Password ({err}). Run op signin first.{RESET}", file=sys.stderr)
        sys.exit(1)
    me = json.loads(stdout)
    title = "Recreate vault permissions"
    line = "─" * (len(title) + 4)
    print(f"\n{CYAN}╭{line}╮{RESET}\n{CYAN}│{RESET}  {BOLD}{title}{RESET}  {CYAN}│{RESET}\n{CYAN}╰{line}╯{RESET}")
    print(f"  {DIM}{'Account':<11}{RESET}{me.get('url', '?').replace('https://', '').rstrip('/')}")
    print(f"  {DIM}{'Signed in':<11}{RESET}{me.get('email', '?')}")
    print(f"  {DIM}{'From':<11}{RESET}{csv_path}")
    print(f"  {DIM}{'Mode':<11}{RESET}{YELLOW if mode != 'Live' else GREEN}{mode}{RESET}")
    return me


# Reads the options and runs the whole thing
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Recreate vault user and group assignments from shared_vaults_permissions_mapping.py's CSV.")
    ap.add_argument("--file", default=str(DEFAULT_CSV), help="The CSV to read (default: vault_access_report.csv here)")
    ap.add_argument("--account", help="1Password account shorthand or sign-in address")
    ap.add_argument("--create-groups", action="store_true",
                    help="Create groups that don't exist here and add their members, without asking")
    ap.add_argument("--no-create-groups", action="store_true", help="Never create groups, and don't ask")
    ap.add_argument("--dry-run", action="store_true", help="Show what would happen without changing anything")
    args = ap.parse_args()

    csv_path = Path(args.file)
    mode = "Dry run" if args.dry_run else "Live"
    me = check_signed_in(args.account, csv_path, mode)
    _logs_dir.mkdir(parents=True, exist_ok=True)
    with _audit_path.open("w", encoding="utf-8") as f:
        f.write(f"Recreate vault permissions\nStarted    {_run_started.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Signed in  {me.get('email', '?')}\nAccount    {me.get('url', '?')}\n"
                f"From       {csv_path.resolve()}\nMode       {mode}\n\n")

    heading("Reading")
    source, members, rows = load_csv(csv_path)
    user_count = len({e for v in source.values() for e in v["users"]})
    group_count = len({g for v in source.values() for g in v["groups"]})
    field("CSV", f"{rows} rows, {len(source)} vaults, {user_count} direct users, {group_count} groups")
    vault_index, user_index, group_index = load_destination(args.account)

    create = args.create_groups
    if not create and not args.no_create_groups:
        create = ask_create_groups(creatable_groups(source, group_index))

    tasks, issues, to_create = plan(source, members, vault_index, user_index, group_index, create)
    matched = len({base_name(t["vault"]["name"]) for t in tasks})
    heading("Plan")
    field("Vaults matched", f"{matched} of {len(source)}")
    field("Assignments to make", len(tasks))
    if to_create:
        field("Groups to create", len(to_create))

    created = {}
    if to_create:
        created = create_all_groups(to_create, members, user_index, args.account, args.dry_run, issues)
        for t in tasks:
            if t["id"] is None:
                t["id"] = created.get(t["name"])
        for t in [t for t in tasks if t["id"] is None]:
            issues.append(make_issue("failed", t["vault"]["name"], "group", t["name"], t["perms"],
                                     "group couldn't be created"))
        tasks = [t for t in tasks if t["id"] is not None]

    heading("Would assign" if args.dry_run else "Assigning")
    granted = 0
    if tasks:
        granted = grant_all(tasks, args.account, args.dry_run, issues)
    else:
        print(f"  {DIM}Nothing to assign{RESET}")
    if issues:
        write_report(issues)
    show_issues(issues)
    sys.exit(summary(granted, len(created), issues, args.dry_run))


if __name__ == "__main__":
    main()
