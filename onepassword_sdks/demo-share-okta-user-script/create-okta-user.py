import os
from okta.client import Client as OktaClient
from okta.models import User, UserProfile, UserCredentials
import asyncio
from onepassword import *
import pyperclip
from dotenv import load_dotenv

load_dotenv()


def validate_email(email):
    """
    Simple email validation
    """
    import re

    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(email_regex, email) is not None


def get_user_input():
    """
    Interactively collect user details
    """
    while True:
        email = input("Enter user email: ").strip()
        if validate_email(email):
            break
        print("Invalid email format. Please try again.")

    first_name = input("Enter first name: ").strip()
    last_name = input("Enter last name: ").strip()
    personal_email = input("Enter user's personal email: ").strip()
    if not validate_email(personal_email):
        print("Invalid personal email format. Please try again.")
        personal_email = input("Enter user's personal email: ").strip()

    return email, first_name, last_name, personal_email


async def create_okta_user(email, first_name, last_name, client, personal_email):
    """
    Create a new user in Okta with the specified details.
    """
    # Okta configuration
    orgUrl = os.getenv("OKTA_ORG_URL")
    config = {
        "orgUrl": orgUrl,
        "token": os.getenv("OKTA_API_TOKEN"),
    }

    # Initialize Okta client
    okta_client = OktaClient(config)

    # Create user profile
    profile = UserProfile(
        {
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "login": email,  # Usually set to email for simplicity
        }
    )

    password = await create_password(client)
    # Create user credentials with password
    credentials = UserCredentials({"password": {"value": password}})

    # Create user object
    user = User({"profile": profile, "credentials": credentials})

    try:
        # Create user in Okta
        created_user, resp, err = await okta_client.create_user(user)

        if err:
            print(f"Error creating user: {err}")
            return None

        print(f"Okta user created successfully: {created_user.id}")
        await save_item(
            client,
            username=email,
            password=password,
            personal_email=personal_email,
            org_url=orgUrl,
        )
        return created_user

    except Exception as e:
        print(f"An error occurred: {e}")
        return None


async def create_password(client):
    random_password = client.secrets.generate_password(
        PasswordRecipeRandom(
            parameters=PasswordRecipeRandomInner(
                length=40,
                includeDigits=True,
                includeSymbols=True,
            )
        ),
    )
    return random_password.password


async def save_item(client, username, password, personal_email, org_url):
    """
    Save the Okta credentials in 1Password
    """
    vault_id = os.getenv("OP_VAULT_ID")
    item = ItemCreateParams(
        title="Okta User Credentials - " + username,
        vault_id=vault_id,
        category=ItemCategory.LOGIN,
        fields=[
            ItemField(
                id="username",
                title="Username",
                value=username,
                fieldType=ItemFieldType.EMAIL,
            ),
            ItemField(
                id="password",
                title="Password",
                value=password,
                fieldType=ItemFieldType.CONCEALED,
            ),
        ],
        websites=[
            Website(
                label="Okta",
                url=org_url,
                autofillBehavior=AutofillBehavior.ANYWHEREONWEBSITE,
            ),
        ],
    )

    try:
        createdItem = await client.items.create(item)
        await create_share_link(client, createdItem, personal_email)
    except Exception as e:
        print(f"Error saving credentials: {e}")


async def create_share_link(
    client: Client,
    item: Item,
    email: str,
) -> str:
    """Create a share link for the note."""
    policy = await client.items.shares.get_account_policy(
        vault_id=item.vault_id, item_id=item.id
    )
    gotten_item = await client.items.get(vault_id=item.vault_id, item_id=item.id)
    recipients = None
    recipients = [
        ValidRecipientEmail(
            type=ValidRecipientTypes.EMAIL,
            parameters=ValidRecipientEmailInner(email=email),
        )
    ]

    try:
        share_result = await client.items.shares.create(
            item=gotten_item,
            policy=policy,
            params=ItemShareParams(
                one_time_only=False,
                expire_after="FourteenDays",
                recipients=recipients,
            ),
        )
        pyperclip.copy(share_result)
        print(f"Share link created: {share_result} - it's on your clipboard!")
        return share_result

    except Exception as e:
        print(f"Error creating share link: {e}")
        sys.exit(1)


async def main():
    print("Okta User Creation Utility")
    print("-------------------------")

    # Gets your service account token from the OP_SERVICE_ACCOUNT_TOKEN environment variable.
    token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")

    # Connects to 1Password. Fill in your own integration name and version.
    client = await Client.authenticate(
        auth=token,
        integration_name="My 1Password Integration",
        integration_version="v1.0.0",
    )

    # Get user input
    email, first_name, last_name, personal_email = get_user_input()

    # Create user in Okta
    await create_okta_user(email, first_name, last_name, client, personal_email)


if __name__ == "__main__":
    asyncio.run(main())
