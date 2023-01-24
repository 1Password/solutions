#!/usr/bin/env python3
import subprocess
import sys


def get_lp_data():
    # Sign user into LastPass
    lp_username = input("You will be prompted once for your LastPass username and twice for your Master Password.\nThe first prompt signs you into the LastPass CLI, the second prompt approves the export.\nWe don't store these credentials and will only be used for this session.\n\nPlease enter your LastPass username.\n>")
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
