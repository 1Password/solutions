#!/usr/bin/env python3
"""
This script:
1. Reads a README.md file from a specified folder
2. Creates a note in 1Password with the README content
3. Adds a specified file from the same folder as an attachment
4. Creates a share link for the note

Uses the official 1Password Python SDK (onepassword).
"""

import asyncio
import os
import sys
import argparse
import pyperclip
from datetime import datetime
from typing import Dict, Optional, List
from onepassword import *


def read_readme(folder_path: str) -> str:
    """Read the README.md file from the specified folder."""
    readme_path = os.path.join(folder_path, "README.md")
    if not os.path.exists(readme_path):
        print(f"Error: README.md not found in {folder_path}")
        sys.exit(1)

    try:
        with open(readme_path, "r", encoding="utf-8") as file:
            content = file.read()
        return content
    except Exception as e:
        print(f"Error reading README.md: {e}")
        sys.exit(1)


async def get_vault_id_by_name(client: Client, vault_name: str) -> Optional[str]:
    """Get the vault ID by name."""
    try:
        vaults = await get_vault_details(client)
        for vault_id, vault_title in vaults.items():
            if vault_title.lower() == vault_name.lower():
                return vault_id

        print(f"Error: Vault '{vault_name}' not found")
        print("Available vaults:")
        for vault in vaults:
            print(f"- {vault.get('name')}")
        sys.exit(1)
    except Exception as e:
        print(f"Error listing vaults: {e}")
        sys.exit(1)


async def create_note_with_readme(
    client: Client, vault_id: str, title: str, content: str, folder_path: str
) -> Item:
    """Create a secure note in 1Password with README content."""
    try:
        # create an empty array of FileCreateParams
        filesToAttach = []
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)

            if os.path.isfile(file_path) and filename != "README.md":
                with open(file_path, "r") as file:
                    # Attach the file to the note
                    file_create_params = FileCreateParams(
                        name=filename,
                        content=file.read(),
                        sectionId="scriptsSection",
                        fieldId=filename,
                    )
                    filesToAttach.append(file_create_params)
                    print(f"File {filename} attached successfully")

        item_create_params = ItemCreateParams(
            vault_id=vault_id,
            category=ItemCategory.SECURENOTE,
            title=title,
            notes=content,
            sections=[ItemSection(id="scriptsSection", title="Scripts")],
            files=filesToAttach,
        )

        item = await client.items.create(item_create_params)

        print(f"Note created successfully with ID: {item.id}")
        return item

    except Exception as e:
        print(f"Error creating note in 1Password: {e}")
        sys.exit(1)


async def create_share_link(
    client: Client,
    item: Item,
    view_once: bool = False,
    expire_after: int = 30,
    emails: Optional[List[str]] = None,
) -> str:
    """Create a share link for the note."""
    expiry_string = get_expiry_string(expire_after)
    policy = await client.items.shares.get_account_policy(
        vault_id=item.vault_id, item_id=item.id
    )
    recipients = None
    if emails:
        recipients = [
            ValidRecipientEmail(
                type=ValidRecipientTypes.EMAIL,
                parameters=ValidRecipientEmailInner(email=email),
            )
            for email in emails
        ]

    try:
        share_result = await client.items.shares.create(
            item=item,
            policy=policy,
            params=ItemShareParams(
                one_time_only=view_once,
                expire_after=expiry_string,
                recipients=recipients,
            ),
        )
        return share_result

    except Exception as e:
        print(f"Error creating share link: {e}")
        sys.exit(1)


async def get_vault_details(client: Client) -> Dict[str, str]:
    """Cache vault details to avoid repeated API calls."""
    vaults = await client.vaults.list_all()
    return {vault.id: vault.title async for vault in vaults}


def get_expiry_string(days: int) -> str:
    """Convert number of days to expiry string format."""
    expiry_map = {1: "OneDay", 7: "SevenDays", 14: "FourteenDays", 30: "ThirtyDays"}
    return expiry_map.get(days, "ThirtyDays")


async def main():
    parser = argparse.ArgumentParser(
        description="Create a 1Password note from README.md and attach files"
    )

    parser.add_argument(
        "folder", help="Path to folder containing README.md and the files to attach"
    )
    parser.add_argument("--vault", "-v", required=True, help="1Password vault name")
    parser.add_argument(
        "--title", "-t", help="Title for the note (default: README + current date)"
    )
    parser.add_argument(
        "--view-once", action="store_true", help="Create a view-once share link"
    )
    parser.add_argument(
        "--expire-after",
        "-e",
        type=int,
        choices=[1, 7, 14, 30],
        default=30,
        help="Number of days the share link is valid (default: 30)",
    )
    parser.add_argument(
        "--emails",
        "-m",
        nargs="+",
        help="List of emails to add as recipients for the share link",
    )

    args = parser.parse_args()

    # Initiate the 1Password client
    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
    client = await Client.authenticate(
        auth=token,
        integration_name="1Password SDK Share Script",
        integration_version="1.0",
    )

    # Get the vault ID from the name
    vault_id = await get_vault_id_by_name(client, args.vault)

    # Get the README content
    readme_content = read_readme(args.folder)

    # Set a default title if not provided
    if not args.title:
        current_date = datetime.now().strftime("%Y-%m-%d")
        args.title = f"README {current_date}"

    # Create the note with the README content
    item = await create_note_with_readme(
        client, vault_id, args.title, readme_content, args.folder
    )

    # Create a share link
    share_link = await create_share_link(
        client, item, args.view_once, args.expire_after, args.emails
    )

    pyperclip.copy(share_link)

    print("\nSummary:")
    print(f"- Note '{args.title}' created in vault '{args.vault}'")
    print(f"- Files attached to the note")
    print(f"- Share link created: {share_link} - it's on your clipboard!")
    print(f"- Link expires in: {args.expire_after} days")
    if args.view_once:
        print("- Link is set to view-once mode")
    if args.emails:
        print(f"- Recipients: {', '.join(args.emails)}")


if __name__ == "__main__":
    asyncio.run(main())
