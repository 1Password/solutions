# Okta User Creation Utility

A Python utility for creating new users in Okta and securely storing their credentials in 1Password, then sharing via a share link.

## Overview

This script streamlines the user onboarding process by:

1. Collecting user information through an interactive prompt
2. Creating a new user account in Okta with a secure random password
3. Storing the credentials in 1Password
4. Creating a share link to securely share credentials with the new user via their personal email

## Requirements

- Python 3.6+
- 1Password Service Account token
- Okta API token with user management permissions
- Python packages:
  - `okta-sdk-python`
  - `onepassword`
  - `pyperclip`
  - `python-dotenv`

## Installation

1. Clone or download this repository
2. Install the required dependencies:

```bash
pip install okta-sdk-python onepassword pyperclip python-dotenv
```

3. Create a `.env` file in the same directory as the script with the following variables:

```
OKTA_ORG_URL=https://your-domain.okta.com
OKTA_API_TOKEN=your-okta-api-token
OP_SERVICE_ACCOUNT_TOKEN=your-1password-service-account-token
OP_VAULT_ID=your-1password-vault-id
```

## Usage

Run the script using Python:

```bash
python okta_user_creation.py
```

The script will:

1. Prompt you for the user's information:
   - Work email address (will be used as username)
   - First name
   - Last name
   - Personal email address (for credential sharing)
2. Create the user in Okta with a secure 40-character random password
3. Store the credentials in 1Password
4. Generate a share link and copy it to your clipboard
5. The share link will be valid for 14 days and can be sent to the user's personal email

## Security Features

- Generates strong 40-character random passwords
- Validates email formats before processing
- Uses one-time share links with 14-day expiration
- Securely stores credentials in 1Password
- Prevents password exposure by sharing directly from 1Password

## Troubleshooting

If you encounter errors:

- Ensure all environment variables are correctly set in the `.env` file
- Verify your Okta API token has sufficient permissions
- Check that your 1Password service account token is valid
- Ensure the specified 1Password vault exists and is accessible

## Limitations

- The script currently only supports basic user creation
- Group assignments and additional Okta profile fields are not included
- Custom password policies are not supported (uses a fixed 40-character random password)
