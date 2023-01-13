#!/usr/bin/env python3
import getopt
import sys
import lpass
from folder_migrate import migrate_folders
from vault_item_import import migrate_items


def main(argv):
    csv_data = ''
    is_migrating_folders = False
    is_migrating_items = False
    opts, args = getopt.getopt(argv, "f:fd:i", ["file=", "folders", "items"])
    for opt, arg in opts:
        if opt == "--file":
            print(f'Export secrets from csv file {arg}')
            with open(arg, newline='') as csvfile:
                csv_data = csvfile.read()
            continue

        if opt in ("-fd", "--folders"):
            is_migrating_folders = True
            continue

        if opt in ("-i", "--items"):
            is_migrating_items = True
            continue

    if len(csv_data) == 0:
        print('Export secrets using lpass cli')
        csv_data = lpass.export_csv()

    if is_migrating_folders:
        print('Migrating folders...')
        migrate_folders(csv_data)

    if is_migrating_items:
        print('Migrating items')
        migrate_items(csv_data)


if __name__ == "__main__":
    main(sys.argv[1:])
