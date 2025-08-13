import os
import logging
import asyncio
import subprocess
import json
import time
from keepercommander import api,cli
from keepercommander.params import KeeperParams
from onepassword import *
from typing import Optional, Dict
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# Set up logging to see the script's progress.
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# 1Password Configuration - Set this environment variable.
# This script uses the official 1Password SDK, which authenticates with a service account token.
ONEPASSWORD_SERVICE_ACCOUNT_TOKEN = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")

# Keeper Configuration - The script will prompt for your Keeper password.
KEEPER_USER = os.getenv("KEEPER_USER")  # Your Keeper email address

# Vault name for 1Password where Keeper records will be migrated. (script will create it)
DEFAULT_1P_VAULT_NAME = "Keeper Import"


# --- 1Password Functions ---


async def get_op_client() -> Optional[Client]:
    """Initializes and returns an authenticated 1Password client using the official SDK."""
    if not ONEPASSWORD_SERVICE_ACCOUNT_TOKEN:
        logging.error(
            "1Password service account token not found. Please set the OP_SERVICE_ACCOUNT_TOKEN environment variable."
        )
        return None
    logging.info("Authenticating with 1Password...")
    try:
        client = await Client.authenticate(
            auth=ONEPASSWORD_SERVICE_ACCOUNT_TOKEN,
            integration_name="Keeper Migration Script",
            integration_version="v2.0.0",
        )
        logging.info("Successfully authenticated with 1Password.")
        return client
    except Exception as e:
        logging.error(f"Failed to authenticate with 1Password: {e}")
        return None


async def create_op_item(client: Client, vault_id: str, keeper_record: dict):
    """Creates a 1Password item from a Keeper record using the official SDK."""
    title = keeper_record.get("title", "No Title")
    logging.info(f"Migrating record: '{title}' to vault '{DEFAULT_1P_VAULT_NAME}'")

    # Prepare fields (username, password, etc.)
    fields = []
    if keeper_record.get("login"):
        fields.append(
            ItemField(
                id="username",
                title="Username",
                value=keeper_record["login"],
                fieldType=ItemFieldType.TEXT,
            ),
        )
    if keeper_record.get("password"):
        fields.append(
            ItemField(
                id="password",
                title="Password",
                value=keeper_record["password"],
                fieldType=ItemFieldType.CONCEALED,
            )
        )
    
    if keeper_record.get("totp"):
        fields.append(
            ItemField(
                id="totp",
                title="totp",
                value=keeper_record["totp"],
                fieldType=ItemFieldType.TOTP,
            )
        )

    # Prepare sections for custom fields
    sections = []
    if keeper_record.get("custom_fields"):
        custom_section = ItemSection(
            id="keeper_custom_fields", label="Keeper Custom Fields"
        )
        sections.append(custom_section)
        for custom_field in keeper_record["custom_fields"]:
            field_label = custom_field.get("name")
            field_value = custom_field.get("value")
            if field_label and field_value:
                fields.append(
                    Field(
                        label=field_label,
                        value=str(field_value),
                        section=custom_section,
                    )
                )

    # Prepare URLs
    urls = []
    if keeper_record.get("login_url"):
        urls.append(
            Website(
                url=keeper_record["login_url"],
                label="Login URL",
                autofillBehavior=AutofillBehavior.ANYWHEREONWEBSITE,
            )
        )

    # Assemble the item parameters for creation
    item_params = ItemCreateParams(
        vault_id=vault_id,
        category=ItemCategory.LOGIN,
        title=title,
        tags=["keeper-migration"],
        fields=fields,
        sections=sections,
        notes=keeper_record.get("notes", ""),
        websites=urls,
    )

    try:
        created_item = await client.items.create(item_params)
        logging.info(
            f"Successfully created item '{created_item.title}' in vault '{DEFAULT_1P_VAULT_NAME}'."
        )
        time.sleep(1)  # To avoid hitting API rate limits
    except Exception as e:
        logging.error(f"Error creating item '{title}' in 1Password: {e}")


def get_keeper_params() -> Optional[KeeperParams]:
    """Initializes and returns Keeper parameters."""
    if not KEEPER_USER:
        logging.error(
            "Keeper username not found. Please set the KEEPER_USER environment variable."
        )
        return None
    params = KeeperParams()
    params.user = KEEPER_USER
    return params


def keeper_login(params: KeeperParams) -> bool:
    """Logs in to Keeper and syncs data."""
    logging.info("Logging in to Keeper...")
    try:
        api.login(params)
        if params.session_token:
            logging.info("Successfully logged in to Keeper. Syncing data...")
            api.sync_down(params)
            logging.info("Keeper data synced.")
            return True
    except Exception as e:
        logging.error(f"Error logging in to Keeper: {e}")
    return False


# --- Keeper Folder Mapping Function ---

def build_record_folder_mapping(params: KeeperParams) -> Dict[str, str]:
    """Returns a mapping of record_uid -> folder_uid from subfolders and shared folders."""
    mapping = {}

    # Subfolders (personal)
    if params.subfolder_cache:
        for folder_uid, folder in params.subfolder_cache.items():
            record_refs = folder.get("records")
            if record_refs:
                for ref in record_refs:
                    if isinstance(ref, dict):
                        record_uid = ref.get("record_uid")
                    else:
                        record_uid = ref
                    if record_uid:
                        mapping[record_uid] = folder_uid

    # Shared folders
    if params.shared_folder_cache:
        for folder_uid, folder in params.shared_folder_cache.items():
            record_refs = folder.get("records")
            if record_refs:
                for ref in record_refs:
                    if isinstance(ref, dict):
                        record_uid = ref.get("record_uid")
                    else:
                        record_uid = ref
                    if record_uid and record_uid not in mapping:
                        mapping[record_uid] = folder_uid

    return mapping


# --- Updated Keeper Records Function ---

def get_keeper_records(params: KeeperParams) -> list:
    """Fetches all records from the Keeper vault and associates them with folders."""
    records = []
    if not params.record_cache:
        logging.warning("Keeper record cache is empty.")
        return records

    record_folder_mapping = build_record_folder_mapping(params)

    for record_uid in params.record_cache:
        record = api.get_record(params, record_uid)
        folder_uid = record_folder_mapping.get(record_uid)
        record_data = {
            "title": record.title,
            "login": record.login,
            "password": record.password,
            "login_url": record.login_url,
            "notes": record.notes,
            "custom_fields": [
                {"name": f.name, "value": f.value} for f in record.custom_fields
            ],
            "folder": folder_uid,  # Now populated
            "totp": record.totp,
        }
        records.append(record_data)
    return records



def get_keeper_folders(params: KeeperParams) -> dict:
    """Fetches all folders from Keeper (subfolders + shared folders)."""
    folders = {}

    if params.folder_cache:
        folders.update({uid: folder["name"] for uid, folder in params.folder_cache.items()})

    if params.shared_folder_cache:
        folders.update({uid: folder["name"] for uid, folder in params.shared_folder_cache.items()})

    return folders


async def create_1p_vault(vault_name: str) -> str:
    """Creates a new vault in 1Password."""
    vault = subprocess.run(
        [
            "op",
            "vault",
            "create",
            vault_name,
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    vault_data = json.loads(vault.stdout)
    return vault_data["id"]


async def main():
    """Main function to run the migration."""
    logging.info(
        "Starting Keeper to 1Password migration using the official Python SDK."
    )

    # --- 1Password Setup ---
    op_client = await get_op_client()
    if not op_client:
        return

    # --- Keeper Setup ---
    keeper_params = get_keeper_params()
    if not keeper_params or not keeper_login(keeper_params):
        return

    vault_id = await create_1p_vault(DEFAULT_1P_VAULT_NAME)

    # --- Fetch All Data ---
    logging.info("Fetching all records and folders from Keeper...")
    keeper_records = get_keeper_records(keeper_params)
    keeper_folders = get_keeper_folders(keeper_params)
    logging.info(
        f"Found {len(keeper_records)} records and {len(keeper_folders)} folders in Keeper."
    )

    # --- Prepare for Migration ---
    # Determine all unique vault names required for the migration
    required_vault_names = {DEFAULT_1P_VAULT_NAME}
    for record in keeper_records:
        folder_uid = record.get("folder")
        if folder_uid and folder_uid in keeper_folders:
            required_vault_names.add(keeper_folders[folder_uid])

    logging.info(f"Required 1Password vaults: {list(required_vault_names)}")

    # --- Run Migration ---
    logging.info("Starting migration of records...")
    for record in keeper_records:
        folder_uid = record.get("folder_uid")

        await create_op_item(op_client, vault_id, record)

    logging.info("Migration script has finished.")


if __name__ == "__main__":
    if not ONEPASSWORD_SERVICE_ACCOUNT_TOKEN or not KEEPER_USER:
        print("--- SETUP REQUIRED ---")
        print("Please set the following environment variables before running:")
        print("  - OP_SERVICE_ACCOUNT_TOKEN: Your 1Password service account token.")
        print("  - KEEPER_USER: Your Keeper email address.")
        print("----------------------")
    else:
        asyncio.run(main())
