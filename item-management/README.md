# Item management scripts

## Introduction

These scripts are examples of how to perform bulk creation, read, update, or delete actions on items in 1Password. As well as an example script to create a temporary 1Password item to use for item sharing.

For more information about managing items with the 1Password command line tool, see the complete documentation for [op item subcommands](https://developer.1password.com/docs/cli/reference/management-commands/item).

## Use-cases


### Bulk selectors

* You can select items based on several criteria, including the the vault they are stored in, one or more tags, or the value of a field, such as website or username.
* Examples of performing bulk actions on every item in a vault:
  * [bulk-update-url-field-by-vault.py](bulk-update-url-field-by-vault.py) or [bulk-update-url-field-by-vault.ps1](bulk-update-url-field-by-vault.ps1)
  * [modify-field-type-by-vault.sh](modify-field-type-by-vault.sh)
* Examples of performing bulk actions on all items with a specific tag:

For more details on how to select items, see [op item list](https://developer.1password.com/docs/cli/reference/management-commands/item#item-list).

### Modify the website value of multiple items

**Requirements**: The Python script requires the `tqdm` package for progress bar functionality. Install it by running:
  ```
  pip install -r requirements.txt
  ```
  
If you need to make the same change to the website field of many items, scripts that provide this functionality in both Python and Powershell are available:

* Python: [bulk-update-url-field-by-vault.py](bulk-update-url-field-by-vault.py)
* Powershell [bulk-update-url-field-by-vault.ps1](bulk-update-url-field-by-vault.ps1).

### Change field type while retaining value

If you have multiple items with incorrect field types but the correct value (e.g., the field is of type `text` but the value is a password, PIN, or other secret), which may happen when importing customized items from outside 1Password, [modify-field-type-by-vault.sh](modify-field-type-by-vault.sh) provides an example of how to convert multiple fields of type `text` to type `password` without changing the value of those fields.

### Share Zoom Recording Link using 1Password Item Share

If you have a Zoom Recording Link that you are looking to share, this script will create a placeholder 1Password Login Item, based off some of the information promoted for. It takes in a standard Zoom Recording link and seperates the two lines out into the URL and Password, to add to the 1Password item accordingly. Lastly it creates a [item-share link](https://developer.1password.com/docs/cli/reference/management-commands/item#item-share) to send out to the provided email addresses. [recording-item-share.sh](recording-item-share.sh) provides an example of how you can utilize the 1Password Item Share to distribute temporary credentials to contacts outside your 1Password account in a secure fashion.

### Create Vault based on item content

 Through this script, [create-vault-based-on-item.sh](create-vault-based-on-item.sh), items in a certain vault are checked, and a new vault is created based of a field in the item. From there the original item is recreated in the new vault and removed from the "landing" vault. The concent behind this, is that perhaps 1Password Connect is in place that is tied to a "landing" vault where new items are being created through a web form and Secrets Automation (this part is not part of the script).
