import subprocess
import getopt
import sys

def main(argv):
    opts, args = getopt.getopt(argv, None, ["file="])
    for opt, arg in opts:
        print(opt)
        print(arg)
        if opt != "--file":
            sys.exit("please use the --file option to specify a path to a file containing a list of vault UUIDs for vaults you'd like to delete.")
    # with open("tests/vaultlist", "r", encoding="utf-8") as vaultList:
        # for vault in vaultList.readlines():
            # subprocess.run(f"op vault delete {vault}", shell=True, check=True, capture_output=True)


main(sys.argv[1:])