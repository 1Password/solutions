# 1Password Note Sharing Script

A Python utility for creating secure notes in 1Password with file attachments and share links. The contents of the note are derived from a `README.md` file located in a specified folder. This script is designed to facilitate secure sharing of documentation and files outside an organization.

## Overview

This script automates the process of:

1. Reading a `README.md` file from a specified folder.
2. Creating a secure note in 1Password with the README content.
3. Attaching specified files from the same folder.
4. Creating a share link for the note with customizable settings.

## Requirements

- Python 3.9+
- A [1Password Service Account](https://developer.1password.com/docs/service-accounts/get-started/) with read, write, and share permissions in the vault where you want to create the item.
- Python packages:
  - `onepassword`
  - `pyperclip`

## Installation

1. Clone or download this repository.
2. Install the required dependencies:

```bash
pip install onepassword
```

3. Make sure you have a 1Password Service Account token set in your environment:

```bash
export OP_SERVICE_ACCOUNT_TOKEN="your-token-here"
```

## Usage

```bash
python3 op_share.py <folder_path> --vault <vault_name> [options]
```

### Required Arguments

- `folder_path`: Path to the folder containing the README.md and files to attach
- `--vault` or `-v`: Name of the 1Password vault to use

### Optional Arguments

- `--title` or `-t`: Custom title for the note (default: "README" + current date)
- `--view-once`: Create a view-once share link (link expires after one viewing)
- `--expire-after` or `-e`: Days until share link expires (1, 7, 14, or 30; default: 30)
- `--emails` or `-m`: Space-separated list of email addresses to share with

## Examples

### Basic Usage

Create a note with the README content and attach all other files from the folder:

```bash
python3 op_share.py ./my_project --vault "Company Vault"
```

### Custom Title and Expiration

```bash
python3 op_share.py ./deploy_scripts --vault "Dev Team" --title "Deployment Instructions" --expire-after 7
```

### Share With Specific Recipients

```bash
python3 op_share.py ./onboarding --vault "HR" --emails john@example.com sarah@example.com --view-once
```

## How It Works

1. The script reads the `README.md` file from the specified folder.
2. It creates a secure note in the specified 1Password vault with the README content.
3. It attaches all other files from the folder to the note.
4. It generates a share link with the specified expiration and recipient settings.
5. It outputs a summary of the actions performed.

## Troubleshooting

If you encounter errors:

- Make sure your 1Password Service Account token is valid and has read, write, and share permissions in the vault.
- Verify the specified vault exists and is accessible.
- Check that the folder contains a `README.md` file.

## Security Considerations

- Service Account tokens have powerful access; store them securely.
- Use the shortest practical expiration time for share links.
- Use view-once links for sensitive information.
