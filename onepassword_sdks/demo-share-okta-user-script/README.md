# Okta User Creation Utility

A Python utility that creates a new user in Okta and stores their Okta credentials in 1Password, then creates a Secure Item Sharing Link for the credentials that can be sent to the new employee's personal email address.

## Overview

This script streamlines the user onboarding process by:

1. Collecting user information through an interactive prompt.
2. Creating a new user account in Okta with a secure random password.
3. Storing the new user's Okta credentials in 1Password.
4. Creating a share link that allows you to securely share the Okta credentials with the new employee by sending the link to their personal email address.

## Requirements

- Python 3.9+
- [1Password Service Account](https://developer.1password.com/docs/service-accounts/get-started/) with read, write, and share permissions in the vault where you want to store the new employee's Okta credentials.
- Okta API token with user management permissions
- Python packages:
  - `okta-sdk-python`
  - `onepassword`
  - `pyperclip`
  - `python-dotenv`

## Installation

1. Clone or download this repository.
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
python create-okta-user.py
```

The script will:

1. Prompt you for the user's information:
   - Work email address (will be used as username)
   - First name
   - Last name
   - Personal email address (for credential sharing)
2. Create the user in Okta with a secure 40-character random password.
3. Store the credentials in 1Password.
4. Generate a share link and copy it to your clipboard.
5. The share link will be valid for 14 days and can be sent to the user's personal email.

## Security Features

- Generates strong 40-character random passwords.
- Validates email formats before processing.
- Uses one-time share links with 14-day expiration.
- Securely stores credentials in 1Password.
- Prevents password exposure by sharing directly from 1Password.

## Troubleshooting

If you encounter errors:

- Make sure all environment variables are correctly set in the `.env` file.
- Verify your Okta API token has sufficient permissions.
- Check that your 1Password service account token is valid and has read, write, and share permissions in the specified vault.
- Make sure the specified 1Password vault exists and is accessible.

## Limitations

- The script currently only supports basic user creation.
- The script does not implement Okta Group assignments nor does it create additional Okta profile fields.
- The script pre-defines a password recipe when generating a password for a newly-created user using a fixed 40-character random password. 1Password SDKs also support [arbitrary password recipes](https://developer.1password.com/docs/sdks/manage-items#generate-a-password).
