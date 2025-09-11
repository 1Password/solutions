import subprocess
import json
import sys


# Check CLI version
def checkCLIVersion():
    r = subprocess.run(["op", "--version", "--format=json"], capture_output=True)
    major, minor = r.stdout.decode("utf-8").rstrip().split(".", 2)[:2]
    if not major == 2 and not int(minor) >= 25:
        sys.exit(
            "❌ You must be using version 2.25 or greater of the 1Password CLI. Please visit https://developer.1password.com/docs/cli/get-started to download the lastest version."
        )


def getVaults():
    try:
        return subprocess.run(
            ["op", "vault", "list", "--permission=manage_vault", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    except Exception as err:
        print(
            f"Encountered an error getting the list of vaults you have access to: ", err
        )
        return


def main():
    checkCLIVersion()
    vaultList = json.loads(getVaults())
    print(
        "Removing 'Imported' prefix from all imported vaults in your 1Password account.\n\n"
    )
    for vault in vaultList:
        vaultID = vault["id"]
        vaultName = vault["name"]
        if vaultName.startswith("Imported "):
            trimmedName = vaultName.removeprefix("Imported ")
            try:
                subprocess.run(
                    ["op", "vault", "edit", vaultID, f"--name={trimmedName}"],
                    check=True,
                    capture_output=True,
                )
                print(f'\t Changed "{vaultName}" => "{trimmedName}"')
            except Exception as err:
                print(f"Encountered an error renaming {vaultName}: ", err)
                continue


main()
