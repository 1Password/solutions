import subprocess
import argparse
import json
import sys

parser = argparse.ArgumentParser("Vault Prefixer", "Provide a path to a list of vault UUIDs.", "Prefixes all vaults passed to the script from the specified file with '!'.")
parser.add_argument("--file", action="store", dest="filepath", help="Required. Specify the path to a file containing a linebreak-delimited list of vault UUIDs you'd like to process.", required=True)
parser.add_argument("-r", action="store_true", dest="deletemode", help="Use this option to delete vaults in the provided list, rather than append `!` to the vault name. USE WITH CAUTION.")
args = parser.parse_args()

# Prefix each vault in the input list with an exclamation mark to make them easy to locate and assess duplicate status. {}
def prefixVault():
    print("Prefixing all listed vaults with '!' for easy sorting and identification.\n\n")
    with open(args.filepath, "r", encoding="utf-8") as vaultList:
        for vault in vaultList:
            vaultID = vault.rstrip()
            try:
                vaultDetails = json.loads(subprocess.run(f"op vault get {vaultID} --format=json", shell=True, check=True, capture_output=True).stdout)
                vaultName = vaultDetails['name']
            except (Exception) as err:
                print(f"Encountered an error getting the details for vault with ID {vaultID}: ", err)
                continue
            try:
                subprocess.run(["op", "vault", "edit", vaultID, f"--name=!{vaultName}"], check=True, capture_output=True)
                print(f"Changed {vaultName} to !{vaultName}")
            except (Exception) as err:
                print(f"Encountered an error renaming {vaultName}: ", err)
                continue
            
# Deletes each vault passed into this script
def deleteVault():
    print("Deleting vaults provided to the script.\n\n")
    # TRIPLE CHECK that the script runner understands the implications of their decision
    understands = False
    if understands == False:
        print("\n\tDELETING VAULTS IS PERMANENT.\n\tBe very sure that you want to delete the vaults you are passing to this script.\n\n")
        response = input("I know what I am doing and UNDERSTAND THAT I CANNOT RESTORE DELETED VAULTS (yes/no): ")
        if response == "yes":
            understands = True
        else:
            sys.exit("If you'd like to proceed with deleting vaults, please run the script again and type 'yes' when prompted.")
    
    with open(args.filepath, "r", encoding="utf-8") as vaultList:
        for vault in vaultList:
            vaultID = vault.rstrip()
            try:
                subprocess.run(f"op vault delete {vaultID}", shell=True, check=True, capture_output=True)
                print(f"Deleted vault {vaultID}")
            except (Exception) as err:
                print(f"Encountered an error deleting vault with ID {vaultID}: ", err)
                continue


if args.deletemode is True:
    deleteVault()
else:
    prefixVault()