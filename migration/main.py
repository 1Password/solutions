#!/usr/bin/env python3
import getopt
import sys
import io
import lpass
from folder_migrate import migrate_folders
from vault_item_import import migrate_items


def main(argv):
    options = {
        'ignore-shared': False,
        'skip-existing': False,
    }
    csvfile = None
    is_migrating_folders = False
    is_migrating_items = False
    opts, args = getopt.getopt(argv, "fi", ["file=", "folders", "items", "ignore-shared", "skip-existing"])
    for opt, arg in opts:
        if opt == "--file":
            print(f'Export secrets from csv file {arg}')
            csvfile = open(arg, newline='')
            continue

        if opt in ("-f", "--folders"):
            is_migrating_folders = True
            continue

        if opt in ("-i", "--items"):
            is_migrating_items = True
            continue

        if opt == "--ignore-shared":
            options["ignore-shared"] = True
            continue

        if opt == "--skip-existing":
            options["skip-existing"] = True
            continue

    if not is_migrating_items and not is_migrating_folders:
        sys.exit("Please specify the flag to run migration -i for items and folders, -f for folders only")

    if is_migrating_items and is_migrating_folders:
        sys.exit("Please specify single flag to run migration -i for items and folders, -f for folders only")

    if not csvfile:
        print('Export secrets using lpass cli.\n')
        csvfile = io.StringIO(lpass.get_lp_data())

    if is_migrating_folders:
        print('Migrating folders:')
        migrate_folders(csvfile, options)
    elif is_migrating_items:
        print('Migrating items:')
        migrate_items(csvfile, options)

    if csvfile:
        csvfile.close()


if __name__ == "__main__":
    main(sys.argv[1:])
