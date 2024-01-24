#!/usr/bin/python3

import subprocess
import random
import json

vaultNamelist = [
    "Radiant Blue Sky",
    "Mountain Adventure",
    "Whimsical Sunflower",
    "Sizzling Tacos-27",
    "Sparkling River",
    "Cosmic Dance Party",
    "Quantum Leap",
    "Midnight Whisper",
    "4 Gleaming Stars",
    "Mystic Moonlight",
    "Enchanted Forest",
    "Turbo-Charged Rocket",
    "Oceanic Dreamscape",
    "Electric Jungle",
    "Velvet Dreams-10",
    "Silver Lining",
    "Wonderland Quest",
    "Solar Eclipse",
    "Lost Balloons-99",
]

itemNamelist = [
    "Ethereal Horizon",
    "Hypnotic Hydra",
    "Harmony Of Numbers",
    "Solarium Symphony",
    "Emerald Dragons",
    "Whirlwind Jubilee",
    "Quantum Quasar",
    "Lost Galaxies",
    "Crimson Velvet",
    "Sapphire Echo",
    "Nebulaic Nectar",
    "Techno Zenith",
    "21 Whispering Pines",
    "Quantum Leap Frog",
    "Celestial Cacophony",
    "Electric Embrace",
    "Serendipity Vortex",
    "Galactics Gazelle",
    "Neon Nocturne",
    "Tranquil Thunder",
    "Pulsar Harmony",
    "Jovian Winds",
    "Echoing Cascade",
    "Nebulaic Nebula",
    "Crystal Lagoon",
    "Lunar Lullaby",
    "Quantum-Quokka",
    "Midnight Monsoon",
    "9-Emerald Enigmas",
    "Electric Equinox",
    "Mystical Mingle",
    "Whispering 33-Willows",
    "Lunar Labyrinth",
    "Sapphire Siesta",
    "Celestial Chaos",
    "Hypnotic Harmony",
    "Quantum Quest",
    "Velvet Vigil",
    "Enigma Ethereal",
    "Crimson Comet",
    "Radiant Rainforest",
    "Techno Tempest",
    "Solar-Symphony_123",
    "Quantum Quartet",
    "Ethereal Eclipse",
    "Electric Eden",
    "Nebulaic Nectarine",
    "Cosmic Carousel",
    "Hypnotic Horizon",
    "Celestial Cerulean",
    "Quantum Quasar Quartet",
    "Serendipity Spectacle",
    "23 Whirling Wonders",
    "Crimson Cascades",
    "Lunar Luminary",
    "Mystic Melange",
    "Electric Ethereal",
    "Nebulaic Nymph",
]


def deleteAllVaults():
    vaultList = json.loads(
        subprocess.run(
            ["op", "vault", "list", "--format=json"],
            check=True,
            capture_output=True,
        ).stdout
    )
    for vault in vaultList:
        id = vault["id"]
        if "Private" not in vault["name"]:
            subprocess.run(
                ["op", "vault", "delete", id],
                check=True,
                capture_output=True,
            ).stdout


def createItems(vaultName):
    for i in range(random.randint(5, 30)):
        itemName = "".join((random.choice(itemNamelist)))
        url = f"https://{vaultName}-{itemName.replace(' ', '')}"
        try:
            subprocess.run(
                f"op item create --title='{itemName}' username=testUser@example.com --vault='{vaultName}' --category=login --generate-password --url='{url}.com'",
                check=True,
                shell=True,
                capture_output=True,
            )
        except Exception as err:
            print(f"There was a problem creating an item: {err}")


def setVaultPermissions(vaultID):
    permissions = "view_items,edit_items,create_items,archive_items,delete_items,view_item_history,view_and_copy_passwords,import_items,copy_and_share_items,manage_vault"
    print(f"setting permissions for vault {vaultID}")
    permissionSet = subprocess.run(
        [
            "op",
            "vault",
            "group",
            "grant",
            f"--vault={vaultID}",
            f"--group=f5pgjqtdfxz3qm2c3jw7w62v5q",
            f"--permissions={permissions}",
            "--no-input",
        ],
        capture_output=True,
    )
    print(permissionSet)


def createVault(vaultName, numOfDupes):
    for i in range(numOfDupes):
        try:
            createdVault = subprocess.run(
                ["op", "vault", "create", vaultName], check=True, capture_output=True
            )
            if i == 0:
                createItems(vaultName)
            if i == 1:
                vaultID = createdVault.stdout.split()[1].decode()
                setVaultPermissions(vaultID)
        except Exception as err:
            print(f"There was a problem creating a vault: {err}")


def main():
    for name in random.sample(vaultNamelist, 10):
        numOfDupes = random.randrange(1, 4)
        createVault(name, numOfDupes)


main()
# deleteAllVaults()
