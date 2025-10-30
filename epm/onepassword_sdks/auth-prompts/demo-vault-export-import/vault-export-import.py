#!/usr/bin/env python3
"""
1Password Vault Manager

This script allows exporting and importing items from a specified vault in 1Password.
It uses AES encryption with a user-provided password and HMAC for integrity verification.
The exported file is named 'employee_export.1password'.

Features:
- Interactive menu for export or import.
- Secure encryption and decryption with password.
- HMAC for tamper detection.
- Visual flair with emojis.

Requirements:
- onepassword-sdk installed.
- cryptography library installed.

Usage:
- Run the script and follow the prompts.
"""

import asyncio
import base64
import json
import logging
import os
import sys
import threading
import time
import argparse
from datetime import datetime
from getpass import getpass
from typing import List, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from onepassword import (
    Client,
    DesktopAuth,
    DocumentCreateParams,
    FileCreateParams,
    ItemCategory,
    ItemCreateParams,
    ItemField,
    ItemFieldType,
    VaultListParams,
    ItemShareDuration,
    ItemShareParams,
)

HMAC_LENGTH = 32

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
logs_dir = os.path.join("logs", timestamp)
os.makedirs(logs_dir, exist_ok=True)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
errors_logger = logging.getLogger("errors")
errors_handler = logging.FileHandler(os.path.join(logs_dir, "errors.log"))
errors_handler.setLevel(logging.ERROR)
errors_logger.addHandler(errors_handler)


def derive_keys(password: str, salt: bytes) -> tuple[bytes, bytes]:
    """Derive encryption key and HMAC key from password and salt using Argon2id."""
    argon2 = Argon2id(
        salt=salt,
        length=64,
        iterations=2,
        lanes=4,
        memory_cost=65536,
    )
    derived = argon2.derive(password.encode())
    enc_key = base64.urlsafe_b64encode(derived[:32])
    hmac_key = derived[32:]
    return enc_key, hmac_key


def compute_hmac(data: bytes, hmac_key: bytes) -> bytes:
    """Compute HMAC-SHA256 of data."""
    h = hmac.HMAC(hmac_key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def print_banner(message: str):
    """Print a banner with emoji flair."""
    print("\n" + "🌟" * 50)
    print(f" {message.center(48)} ")
    print("🌟" * 50 + "\n")


def spinner_func(
    message: str,
    done_event: threading.Event,
    completed: Optional[list] = None,
    total: Optional[int] = None,
):
    """Spinner function to run in a separate thread, optionally with progress count."""
    chars = "|/-\\"
    i = 0
    while not done_event.is_set():
        if completed is not None and total is not None:
            sys.stdout.write(f"\r{message} {completed[0]} of {total} {chars[i % len(chars)]}")
        else:
            sys.stdout.write(f"\r{message} {chars[i % len(chars)]}")
        sys.stdout.flush()
        i += 1
        time.sleep(0.1)
    if completed is not None and total is not None:
        sys.stdout.write(f"\r{message} {completed[0]} of {total} ✅\n")
    else:
        sys.stdout.write(f"\r{message} ✅\n")
    sys.stdout.flush()


async def fetch_item_details(client: Client, vault_id: str, overview):
    """Fetch full item details asynchronously."""
    return await client.items.get(vault_id=vault_id, item_id=overview.id)


async def fetch_content(client: Client, vault_id: str, item_id: str, attr):
    """Fetch file content asynchronously."""
    return await client.items.files.read(vault_id, item_id, attr)


async def export_vault(client: Client, vault_id: str) -> List[dict]:
    """Export items from the specified vault as a list of dicts."""
    print_banner("🔄 Exporting from Specified Vault 🔄")
    items_overview = await client.items.list(vault_id=vault_id)
    total_items = len(items_overview)
    if total_items == 0:
        print("❌ No items found in the vault.")
        return []
    print(f"✅ Found {total_items} items in the vault.\n")

    # Setup export log
    export_logger = logging.getLogger("export")
    export_handler = logging.FileHandler(os.path.join(logs_dir, "export.log"))
    export_handler.setLevel(logging.INFO)
    export_logger.addHandler(export_handler)
    export_logger.propagate = False

    done_event = threading.Event()
    spinner_thread = threading.Thread(target=spinner_func, args=("Gathering item details...", done_event))
    spinner_thread.start()

    # Parallelize fetching full items
    full_items_tasks = [fetch_item_details(client, vault_id, overview) for overview in items_overview]
    full_items = await asyncio.gather(*full_items_tasks, return_exceptions=True)

    done_event.set()
    spinner_thread.join()

    export_items = []
    for index, full_item in enumerate(full_items, start=1):
        sys.stdout.write(f"\r📄 Processing item {index} of {total_items}")
        sys.stdout.flush()
        if isinstance(full_item, Exception):
            errors_logger.error(f"Error fetching item {items_overview[index - 1].title}: {str(full_item)}")
            continue
        overview = items_overview[index - 1]
        export_logger.info(f"Item {index}: Title: {overview.title}, ID: {overview.id}")
        try:
            item_dict = full_item.model_dump(by_alias=True)
            # Remove fields that shouldn't be in create params
            item_dict.pop("id", None)
            item_dict.pop("vault", None)
            item_dict.pop("created_at", None)
            item_dict.pop("updated_at", None)
            item_dict.pop("favorite", None)
            item_dict.pop("state", None)
            item_dict.pop("version", None)
            # Remove original 'files' and 'document' to avoid validation issues on import
            item_dict.pop("files", None)
            item_dict.pop("document", None)

            # Handle attached files
            attached_files = []
            if full_item.files:
                contents = await asyncio.gather(
                    *[fetch_content(client, vault_id, full_item.id, f.attributes) for f in full_item.files],
                    return_exceptions=True,
                )
                for f, content in zip(full_item.files, contents):
                    if isinstance(content, Exception):
                        export_logger.error(f"Error fetching attachment for field_id: {f.field_id}: {str(content)}")
                        continue
                    export_logger.info(f"    Fetched {len(content)} bytes for attachment {f.attributes.name}")
                    file_dict = {
                        "name": f.attributes.name,
                        "content": base64.b64encode(content).decode(),
                        "section_id": f.section_id,
                        "field_id": f.field_id,
                    }
                    attached_files.append(file_dict)

            # Handle documents
            document = None
            if full_item.category == ItemCategory.DOCUMENT and full_item.document:
                export_logger.info(f"    Fetching document for item: {full_item.title}")
                doc = full_item.document
                if isinstance(doc, dict):
                    doc = FileAttributes(**doc)
                content = await client.items.files.read(vault_id, full_item.id, doc)
                export_logger.info(f"    Fetched {len(content)} bytes for document {doc.name}")
                document = {
                    "name": doc.name,
                    "content": base64.b64encode(content).decode(),
                }

            if document:
                item_dict["document"] = document
            if attached_files:
                item_dict["attached_files"] = attached_files

            export_items.append(item_dict)
        except Exception as e:
            errors_logger.error(f"Error processing item {overview.title}: {str(e)}")
            sys.stdout.write("\n")
            print(f"❌ Error processing item {overview.title}: {str(e)}")

    sys.stdout.write("\n")
    export_logger.removeHandler(export_handler)
    export_handler.close()

    return export_items


async def import_item(
    client: Client,
    target_vault_id: str,
    item_dict: dict,
    index: int,
    import_logger,
    errors_logger,
    completed,
    lock,
    semaphore,
):
    async with semaphore:
        import_logger.info(f"Item {index}: Title: {item_dict.get('title', 'Untitled')}")
        try:
            item_dict["vaultId"] = target_vault_id
            temp_dict = item_dict.copy()
            attached_files = temp_dict.pop("attached_files", [])
            document = temp_dict.pop("document", None)
            create_params = ItemCreateParams.model_validate(temp_dict)
            if document:
                if "content" in document:
                    document["content"] = base64.b64decode(document["content"])
                    create_params.document = DocumentCreateParams(
                        name=document["name"],
                        content=document["content"],
                    )
                else:
                    print(f"❌ Skipping document for item due to missing content: {item_dict.get('title', 'Unknown')}")
                    return
            create_params.files = []
            for file_dict in attached_files:
                if "content" in file_dict:
                    file_dict["content"] = base64.b64decode(file_dict["content"])
                    file_params = FileCreateParams(
                        name=file_dict["name"],
                        content=file_dict["content"],
                        section_id=file_dict.get("section_id", ""),
                        field_id=file_dict.get("field_id", ""),
                    )
                    create_params.files.append(file_params)
                else:
                    print(f"❌ Skipping file for item due to missing content: {item_dict.get('title', 'Unknown')}")
            created_item = await client.items.create(params=create_params)
            import_logger.info(f"Imported item ID: {created_item.id}")
        except Exception as e:
            errors_logger.error(f"Error importing item {item_dict.get('title', 'Untitled')}: {str(e)}")
            print(f"❌ Error importing item {item_dict.get('title', 'Untitled')}: {str(e)}")
        finally:
            async with lock:
                completed[0] += 1


async def import_vault(client: Client, target_vault_id: str, import_data: bytes):
    """Import items into the specified vault."""
    print_banner("🔄 Importing to Specified Vault 🔄")
    import_items: List[dict] = json.loads(import_data.decode())
    total_items = len(import_items)
    print(f"✅ Found {total_items} items to import.\n")

    # Setup import log
    import_logger = logging.getLogger("import")
    import_handler = logging.FileHandler(os.path.join(logs_dir, "import.log"))
    import_handler.setLevel(logging.INFO)
    import_logger.addHandler(import_handler)
    import_logger.propagate = False

    lock = asyncio.Lock()
    completed = [0]
    semaphore = asyncio.Semaphore(50)

    tasks = [
        import_item(
            client,
            target_vault_id,
            item_dict,
            index,
            import_logger,
            errors_logger,
            completed,
            lock,
            semaphore,
        )
        for index, item_dict in enumerate(import_items, start=1)
    ]

    done_event = threading.Event()
    spinner_thread = threading.Thread(
        target=spinner_func, args=("📄 Importing item", done_event, completed, total_items)
    )
    spinner_thread.start()

    await asyncio.gather(*tasks)

    done_event.set()
    spinner_thread.join()

    import_logger.removeHandler(import_handler)
    import_handler.close()


async def create_share_link(client: Client, item):
    policy = await client.items.shares.get_account_policy(item.vault_id, item.id)

    # Prompt for recipients
    recipients_input = input("Enter recipients (emails or domains, comma-separated, or leave empty for anyone with the link): ").strip()
    recipients = [r.strip() for r in recipients_input.split(',') if r.strip()] if recipients_input else []

    if recipients:
        valid_recipients = await client.items.shares.validate_recipients(policy, recipients)
    else:
        valid_recipient = []

    # Prompt for expiration
    expire_options = {
        '1': ItemShareDuration.ONEHOUR,
        '2': ItemShareDuration.ONEDAY,
        '3': ItemShareDuration.SEVENDAYS,
        '4': ItemShareDuration.FOURTEENDAYS,
        '5': ItemShareDuration.THIRTYDAYS,
    }
    print("Choose expiration duration:")
    print("1: One Hour")
    print("2: One Day")
    print("3: Seven Days")
    print("4: Fourteen Days")
    print("5: Thirty Days")
    expire_choice = input("Enter choice (1-5): ").strip()
    expire_after = expire_options.get(expire_choice, ItemShareDuration.SEVENDAYS)

    # Prompt for one time only
    one_time_only_input = input("One time only? (y/n): ").strip().lower()
    one_time_only = one_time_only_input == 'y'

    share_params = ItemShareParams(
        recipients=valid_recipients if recipients else [],
        expireAfter=expire_after,
        oneTimeOnly=one_time_only,
    )

    share_link = await client.items.shares.create(item, policy, share_params)
    return share_link


async def run(args):
    print_banner("1Password Vault Manager")

    account = args.account
    if account is None:
        account = input("Enter your 1Password account name (as shown in the app): ")

    # Authenticate using DesktopAuth
    client = await Client.authenticate(
        auth=DesktopAuth(account_name=account),
        integration_name="Vault Manager",
        integration_version="1.0.0",
    )

    # List all vaults with decryptDetails=True
    params = VaultListParams(decryptDetails=True)
    vaults = await client.vaults.list(params=params)

    action = args.action
    if action is None:
        action = input("Choose action: [E]xport or [I]mport? ").strip().upper()
    else:
        action = action.upper()

    vault_names_input = args.vault
    if vault_names_input is None:
        if action == "E":
            vault_names_input = input("Enter the name(s) of the vault(s) to export from (comma-separated): ").strip()
        elif action == "I":
            vault_names_input = input("Enter the name of an existing vault to import into: ").strip()
    else:
        vault_names_input = vault_names_input.strip()

    if action == "E":
        vault_list = [v.strip() for v in vault_names_input.split(',')]
        exported_data = {"exported_vaults": [], "items": []}
        for v_name in vault_list:
            export_vault_obj = None
            while export_vault_obj is None:
                export_vault_obj = next((vault for vault in vaults if vault.title == v_name), None)
                if export_vault_obj is None:
                    print(f"❌ No vault named '{v_name}' found.")
                    v_name = input("Enter another vault name: ").strip()
            export_items = await export_vault(client, export_vault_obj.id)
            if not export_items:
                print(f"❌ Export failed for vault '{v_name}'.")
                continue
            for item in export_items:
                item['original_vault'] = v_name
            exported_data["items"].extend(export_items)
            exported_data["exported_vaults"].append(v_name)

        if not exported_data["items"]:
            print("❌ No data exported.")
            return

        print_banner("🔒 Secure Your Export 🔒")
        password = getpass("🔑 Enter a strong password for encryption: ")
        confirm_password = getpass("🔑 Confirm your password: ")
        if password != confirm_password:
            print("❌ Passwords do not match.")
            return

        if len(exported_data["exported_vaults"]) > 1:
            filename = f"multiple_vaults_export_{timestamp}.1password"
        else:
            filename = f"{exported_data['exported_vaults'][0]}_export_{timestamp}.1password"

        salt = os.urandom(16)
        enc_key, hmac_key = derive_keys(password, salt)
        fernet = Fernet(enc_key)
        encrypted = fernet.encrypt(json.dumps(exported_data).encode())
        hmac_value = compute_hmac(encrypted, hmac_key)
        with open(filename, "wb") as f:
            f.write(salt + hmac_value + encrypted)
        full_path = os.path.abspath(filename)
        print(f"\n✅ Exported successfully!")
        print(f"📁 File: {full_path}")

        # Read the exported file content for attachment
        with open(filename, "rb") as f:
            export_file_content = f.read()

        # Create secure note in Private vault with attached export file
        private_vault = next((v for v in vaults if v.title == "Private"), None)
        if private_vault is None:
            print("❌ Private vault not found. Skipping secure note creation.")
        else:
            vaults_list_str = ", ".join(exported_data["exported_vaults"])
            create_params = ItemCreateParams(
                title=f"Export Backup {timestamp}",
                category=ItemCategory.SECURENOTE,
                vault_id=private_vault.id,
                notes=f"Exported vaults: {vaults_list_str}\nExported file path: {full_path}",
                fields=[
                    ItemField(
                        id="encryption_password",
                        title="Encryption Password",
                        field_type=ItemFieldType.CONCEALED,
                        value=password,
                    )
                ],
                files=[
                    FileCreateParams(
                        name=filename,
                        content=export_file_content,
                        section_id="",
                        field_id="export_file",
                    )
                ],
            )
            try:
                created_item = await client.items.create(params=create_params)
                print(f"✅ Secure note created in Private vault with ID: {created_item.id}")

                # Prompt for share link
                want_share = input("Do you want to create a share link for this secure note? (y/n): ").strip().lower()
                if want_share == 'y':
                    share_link = await create_share_link(client, created_item)
                    print(f"✅ Share link created: {share_link}")
            except Exception as e:
                print(f"❌ Error creating secure note: {str(e)}")
    elif action == "I":
        filename = args.file
        if filename is None:
            filename = input("Enter the path to the export file: ").strip()
        if not os.path.exists(filename):
            print(f"❌ File {filename} not found.")
            return

        with open(filename, "rb") as f:
            data = f.read()

        salt = data[:16]
        hmac_value = data[16 : 16 + HMAC_LENGTH]
        encrypted = data[16 + HMAC_LENGTH :]

        print_banner("🔓 Unlock Your Import 🔓")
        password = getpass("🔑 Enter the password to decrypt: ")

        enc_key, hmac_key = derive_keys(password, salt)
        if compute_hmac(encrypted, hmac_key) != hmac_value:
            print("❌ HMAC verification failed. File may be tampered.")
            return

        fernet = Fernet(enc_key)
        try:
            decrypted = fernet.decrypt(encrypted)
        except InvalidToken:
            print("❌ Invalid password or corrupted file.")
            return

        import_data = json.loads(decrypted.decode())
        if isinstance(import_data, list):
            items = import_data
            exported_vaults = ["Unknown"]
        elif isinstance(import_data, dict) and "items" in import_data and "exported_vaults" in import_data:
            items = import_data["items"]
            exported_vaults = import_data["exported_vaults"]
        else:
            print("❌ Invalid export format.")
            return

        print(f"Exported vaults in file: {', '.join(exported_vaults)}")
        selected_vault = input("Enter the name of the exported vault to import (or 'all' for all): ").strip()

        if selected_vault.lower() != 'all':
            items = [item for item in items if item.get('original_vault') == selected_vault]
            if not items:
                print(f"❌ No items found for vault '{selected_vault}'.")
                return

        target_vault_name = vault_names_input
        target_vault = None
        while target_vault is None:
            target_vault = next((vault for vault in vaults if vault.title == target_vault_name), None)
            if target_vault is None:
                print(f"❌ No vault named '{target_vault_name}' found.")
                target_vault_name = input("Enter another vault name: ").strip()

        await import_vault(client, target_vault.id, json.dumps(items).encode())
        print("✅ Import completed successfully.")
    else:
        print("❌ Invalid action.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="1Password Vault Manager")
    parser.add_argument("--account", required=False, help="1Password account name (as shown in the app)")
    parser.add_argument("--action", required=False, choices=['E', 'I', 'e', 'i'], help="E for export, I for import")
    parser.add_argument("--vault", required=False, help="Name of the vault (source for export, target for import)")
    parser.add_argument("--file", required=False, help="Path to the export file (required for import)")

    args = parser.parse_args()

    asyncio.run(run(args))