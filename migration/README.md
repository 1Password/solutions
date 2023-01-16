# Advanced LastPass migration tools

## Table of Contents

* [Migrate folders and login items from LastPass](#migrate-folders-and-login-items-from-lastpass)
* [Create 1Password vaults based on LastPass folders](#create-1password-vaults-based-on-lastpass-folders)

## Dependencies

* Python
* [1Password CLI](https://developer.1password.com/docs/cli)
  * Ensure you have added your 1Password account to the 1Password CLI and have signed in using `op signin` or `eval $(op signin)` prior to executing the script.
* Optionally the [LastPass CLI](https://github.com/LastPass/lastpass-cli)

## Who is this for?

This script is best run by a LastPass administrator or Superadmin, or anyone else responsible for migrating a large number of LastPass folders to 1Password.

To avoid duplicating labour, creating duplicate items, or duplicate vaults, you may delegate the migration of specific shared folders to certain people, or all shared folders to a single administrator. You may want to revoke other people's access to shared folders during the migration to avoid them showing up in multiple people's exports  and ensure that each shared folder and it's items are migrated exactly one time.

## Migrate folders and login items from LastPass

You can use this script to migrate both your LastPass Sites and Folders to 1Password. LastPass Site items will be converted to 1Password Login items. LastPass Folders will be converted into 1Password Vaults. Nested folders in LastPass will result in separate, non-nested vaults created as siblings to their parent. Items not belonging to any shared folder will be created in the user's Private vault.

This script uses the 1Password CLI tool to import items from either

* a .csv file on your local machine exported from LastPass's web export or
* directly from the LastPass CLI tool.

(this script has not been tested on exports from the LastPass browser extension or other methods).

### Usage

```bash
# Executes the script (vault_item_import.py) and ingests data directly from LastPass CLI without writing files to disk. Creates items and converts LastPass folders to vaults. 
python main.py [--items, -i]

# Executes the script (vault_item_import.py) with the export.csv file located on local machine
python main.py [--items, -i] --file=path_to_csv_file
```

## Create 1Password vaults based on LastPass folders

You can alternatively use this set of scripts to only convert LastPass folders to 1Password vaults without importing your LastPass items. This takes as its input either a LastPass export `.csv` based on the `grouping` columng, or accepts data directly from the LastPass CLI.

This script is a good accompaniment to the the [LastPass importer at 1Password.com](https://support.1password.com/import-lastpass/). For example, if you are responsible for migrating a large number of shared LastPass items and folders, you might consider:

1. Export all items and folders you are responsible for from LastPass.
2. Use the web importer to import the LastPass data. This data will end up in a single 1Password vault. Each item will be tagged with the LastPass folder that previously contained it.
3. Run this script such that it only creates 1Password vaults from your LastPass Folders using either the `.csv` exported from LastPass or the LastPass CLI.
4. Using 1Password's [desktop application](https://1password.com/downloads/), select all items associated with a given tag and move them to the vault of the same name.
5. Log into 1Password.com and grant the people or groups access to each vault and set their permissions as needed.

### Usage

```bash
# Executes the script in Folder Only mode (folder_migrate.py), ingesting data directly from LastPass CLI without writing files to disk. 
python main.py [--folders, -f]

# Executes the script in Folder Only mode (folder_migrate.py) with export.csv file located on local machine
python main.py [--folders, -f] --file=path_to_csv_file
```

* Running the script with the folder only option does not create items in 1Password.
* Running the script with the folder only option will not create multiple vaults of the same name. If you have two LastPass folders with the same name, only one 1Password vault will be created.
* 1Password does not have the concept of nested vaults. If you have nested LastPass folders, they will be created as their own 1Password vault and will be a sibling to their parent.

## Consider 1Password's browser-based importer

If you do not feel comfortable or are unable to run scripts on your device, or you prefer a simpler solution to migrating your items from LastPass to 1Password, 1Password offers a fast, reliable, and secure [importer for your LastPass data](https://support.1password.com/import-lastpass/), which you can access by logging into your 1Password account.

Our browser based importer will handle multiple item types. This import script will only import login items (LastPass "sites") and will disregard all other item types (e.g., Credit Cards, Secure Notes, etc). You should also use the browser-based importer if you want to import different types of items, as this script **only handles LastPass "site"/login items and disregards all other item types**.

You can learn more about importing your items from LastPass using our browser-based importer here: <https://support.1password.com/import-lastpass/>

Note that unlike the browser-based importer, this script will create vaults for any LastPass folders you are migrating, and items will be created in the 1Password vault the corresponds to it's containing LastPass folder.

## Notes

### Handling nested folders

Note that 1Password does not have the concept of nested vaults. If you have nested LastPass folders, they will be created as their own 1Password vault, and will be a sibling to their parent. Vault names reflect the original hierarchy and will have a name similar to `parent_child`

### Limitations

**This script only migrates LastPass Sites**. It will not migrate credit cards, secure notes, or any other item type. You might consider extracting secure notes (all of which have the URL `http://sn` in the LastPass export file) into its own .csv file and use the [LastPass importer at 1Password.com](https://support.1password.com/import-lastpass/), which does handle Secure Notes. Imported secure notes will be tagged with the LastPass folder they were a part of, allowing you to use a 1Password application to move imported secure notes to the appropriate vault based on the tag.

**Migrations will not include TOTP secrets when LastPass CLI is the data source**. The LastPass CLI does not include TOTP secrets in it's exports. Therefore if you use the CLI->CLI migration mode, you will have to manually migrate your TOTP secrets.

**This script will substitute underscore `_` characters for `\` or `/` in Folder Names** for compatibility with the 1Password CLI and [Secret References](https://developer.1password.com/docs/cli/secret-references).

### Unencrypted exports

The LastPass export is unencrypted. As such, additional precuations are necessary to maintain the confidentiality of the data in your exports. This script has the ability to read data directly from the LastPass CLI, avoiding writing secrets to disk.

However, if you cannot use the LastPass CLI and must provide a .csv file from your local computer, prior to exporting your LastPass data, consider the following steps:

1. Ensure you are using a computer you trust and which you do not suspect of being compromised in any way.
2. Disable all backup software prior to exporting your LastPass data.
3. Delete the LastPass export file immidately after running this script.
4. Re-enable any backup software you were previously running.

### Private folders

Please note that there is no mechanism to migrate other users' private LastPass items on their behalf. This means if you are part of an organization, each of your team members will have to migrate their own private LastPass data to their 1Password account. For this, we strongly recommend the [LastPass importer at 1Password.com](https://support.1password.com/import-lastpass/).

### Shared folders

The LastPass exporter may include all shared folders a user has access to. This means shared folders my appear in multiple people's LastPass exports. To avoid duplicating shared items and vaults upon migration, you may want to coordinate who migrates shared folders. For example, you may delegate the migration specific shared folders to certain people, or all shared folders to a single administrator. You may want to revoke other people's access to shared folders during the migration to avoid them showing up in multiple people's exports  and ensure that each shared folder and it's items are migrated exactly one time.

### Vault permissions

After running this import script, you will need to grant groups and individuals access to any shared vaults they should have access to and set their permissions appropriately. For information about vault permissions in 1Password see [Create, share, and manage vaults in your team](https://support.1password.com/create-share-vaults-teams/) (for Business customers) and [Create and share vaults](https://support.1password.com/create-share-vaults/) (for 1Password Families customers).

## Issues

If you encounter any bugs, odd behaviour, or have suggestions for enhancements, please [open an issue](https://github.com/1Password/solutions/issues) and we will consider your suggestion.
