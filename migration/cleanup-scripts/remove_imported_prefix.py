import subprocess
import json


def getVaults():
    try:
        return subprocess.run("op vault list --group=Owners --format=json", shell=True, check=True, capture_output=True).stdout
    except (Exception) as err:
        print(f"Encountered an error getting the list of vaults you have access to: ", err)
        return

def main():
    vaultList = json.loads(getVaults())
    print("Removing 'Imported' prefix from all imported vaults in your 1Password account.\n\n")
    for vault in vaultList:
        vaultID = vault["id"]
        vaultName = vault["name"]
        if (vaultName.startswith("Imported ")):
            trimmedName = vaultName.removeprefix("Imported ")
            try:
                subprocess.run(["op", "vault", "edit", vaultID, f"--name={trimmedName}"], check=True, capture_output=True)
                print(f"\t Changed \"{vaultName}\" => \"{trimmedName}\"")
            except (Exception) as err:
                print(f"Encountered an error renaming {vaultName}: ", err)
                continue

main()