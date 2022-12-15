# Item management scripts

## Introduction

These scripts are examples of how to perform bulk creation, read, update, or delete actions on items in 1Password. As well as an example script to create a temporary 1Password item to use for item sharing. 

For more information about managing items with the 1Password command line tool, see the complete documentation for [op item subcommands](https://developer.1password.com/docs/cli/reference/management-commands/item).

## Use-cases

### Bulk item creation from input file

The script and example input file in [create-items-from-input](create-items-from-input) show how you can create items based on an input file list. This specific example generates a password at item creation time. Passwords could also be passed in from the input file, if desired.

### Bulk selectors

* You can select items based on several criteria, including the the vault they are stored in, one or more tags, or the value of a field, such as website or username.
* Examples of performing bulk actions on every item in a vault:
  * [bulk-update-url-field-by-vault.sh](bulk-update-url-field-by-vault.sh)
  * [modify-field-type-by-vault.sh](modify-field-type-by-vault.sh)
* Examples of performing bulk actions on all items with a specific tag:
  * [bulk-update-username-by-tag.sh](./bulk-update-username-by-tag.sh)

For more details on how to select items, see [op item list](https://developer.1password.com/docs/cli/reference/management-commands/item#item-list).

### Modify the website value of multiple items

If you have a large number of items that require identical changes to the value of the website field, the [bulk-update-url-field-by-vault.sh](bulk-update-url-field-by-vault.sh) is a starting point for such a script.

### Modify the username of multiple items

If you have a large number of items requiring identical changes to the username field [bulk-update-username-by-tag.sh](bulk-update-username-by-tag.sh) is one possible approach.

### Change field type while retaining value

If you have multiple items with incorrect field types but the correct value (e.g., the field is of type `text` but the value is a password, PIN, or other secret), which may happen when importing customized items from outside 1Password, [modify-field-type-by-vault.sh](modify-field-type-by-vault.sh) provides an example of how to convert multiple fields of type `text` to type `password` without changing the value of those fields.

### Share Zoom Recording Link using 1Password Item Share

If you have a Zoom Recording Link that you are looking to share, this script will create a placeholder 1Password Login Item, based off some of the information promoted for. It takes in a standard Zoom Recording link and seperates the two lines out into the URL and Password, to add to the 1Password item accordingly. Lastly it creates a [item-share link](https://developer.1password.com/docs/cli/reference/management-commands/item#item-share) to send out to the provided email addresses. [recording-item-share.sh](recording-item-share.sh) provides an example of how you can utilize the 1Password Item Share to distribute temporary credentials to contacts outside your 1Password account in a secure fashion. 