#!/usr/bin/env python3
import subprocess
import sys


def get_lp_data():
    # Sign user into LastPass
    lp_username = input("Please enter your LastPass username ")
    try:
        subprocess.run(["lpass", "login", lp_username])
    except:
        sys.exit("Unable to sign into LastPass")

    # Issue export command to lpass
    try:
        lp_export = subprocess.run(["lpass", "export"], text=True, capture_output=True).stdout
    except:
        sys.exit("Unable to retrieve LastPass data")

    if len(lp_export) == 0:
        sys.exit("No items were exported from LastPass")

    return lp_export


def prepare_csv(exported_data: str):
    return list(filter(lambda row: (len(row) > 0), exported_data.split("\n")))


def export_csv():
    return prepare_csv(get_lp_data())
