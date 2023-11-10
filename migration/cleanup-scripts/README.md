# LastPass Migration Cleanup Scripts

This is a collection of scripts that can help you clean up your 1Password account after performing a migration from LastPass. 

## Contents

* [`vault_dedupe_helper.py`](#identify-duplicate-vaults-for-removal-with-vault_dedupe_helperpy) generates a report for all shared vaults in your account that can help you identify which duplicates to delete, and which to retain. 
* [`add_vault_prefix.py`](#further-investigate-or-delete-potential-duplicate-vaults-with-add_vault_prefixpy) can take a list of vault UUIDs and prefix each vault name with `!` to make them easy to identify in 1Password for further assessment. Alternatively using the `--delete` option will delete each vault provided in the list. 
* [`remove_imported_prefix.py`](#remove-imported-prefix-from-imported-vaults-with-remove_imported_prefixpy) will remove the "Imported " prefix from the name of all vaults in your 1Password account. Handy to clean things up once you have finalized your migration. 
* [`recreate_metadata_entry.py`](#recreate-metadata-entry) will reconstruct the metadata entries in the metadata vault to point to the oldest imported vaults

> **note**  
> Learn more about migrating your data from LastPass to 1Password [here](https://support.1password.com/import-lastpass/).  

## Identify duplicate vaults for removal with [`vault_dedupe_helper.py`](./vault_dedupe_helper.py)

This script will create a CSV file (`vaultreport.csv`) to help you identify duplicate vaults that may have been created under certain circumstances (for example, when multiple members of your 1Password account used the LastPass importer). The CSV file will be created in the same directory as the script.

### Usage
`python3 vault_dedupe_helper.py`

The script has no options and requires no input. It assumes you have signed in to your 1Password account as a member of the Owners group using `op signin` or `eval $(op signin)`. 

The generated report will list all shared vault in your account, with columns for:
```
vault name, vault UUID, item count, vault creation date, vault updated, number of users
```

With this information, you can determine which duplicate may be worth retaining, and which can be deleted. 

For example, among a set of identically-named vaults, you might keep the one that has a slightly different number of items, and which more than one person has access to. These might suggest that this vault, and not the other duplicates, is the one currently being used. 

There may be other criteria that you can use to determine which duplicates should be removed. 

> **Warning**  
> This script should be run by a member of the Owners group of your 1Password account. 

Once you have identified candidates for removmal, you can copy the UUIDs of those vaults into a separate file containing only a list of linebreak-delimited vault UUIDS for further processing, such as by the [`add_vault_prefix.py`](#further-investigate-or-delete-potential-duplicate-vaults-with-add_vault_prefixpy) script, or a script of your own. That list should be formatted as:

```
wupizr5o5z4vrehdjsaaicr2cu
mvdcqrmfg7a7osxjz5lu76fyra
n7gh6luc2x53losrps2rgjx65a
evorxmphuygomvsuwdroo2nnq4
...
```

## Further investigate or delete potential duplicate vaults with [`add_vault_prefix.py`](./add_vault_prefix.py)
This script will apply `!` as a prefix to all vaults provided as a list of vault UUIDs to the script. The script requires the `--file` flag, which must point to a file containing a linebreak-deliminted list of vault UUIDs. Use the `--delete` option to permanently delete the vaults from your 1Password account instead. 

### Usage

`python3 add_vault_prefix.py --file=path/to/vaultList [OPTIONS]`

`--file` should be a path to a file containing a list of vault UUIDs (and nothing else)

`--delete` runs the script in Delete Mode, permanently deleting from your 1Password account all vaults in the provided list. 

It assumes you have signed in to your 1Password account as a member of the Owners group using `op signin` or `eval $(op signin)`. 

> **warning**  
> Deleting vaults is _irreversible_. Be extremely careful running this script in Delete Mode. You may want to run the script in default mode to ensure that you have selected the correct vault candidates for deletion.  

### Format for vault list file
The script expects a file containinga list of vault UUIDs formatted in this way:
```
wupizr5o5z4vrehdjsaaicr2cu
mvdcqrmfg7a7osxjz5lu76fyra
n7gh6luc2x53losrps2rgjx65a
evorxmphuygomvsuwdroo2nnq4
...
```

This allows you to easily sort all vaults identified using the [`vault_dedupe_helper.py`](#identify-duplicate-vaults-for-removal-with-vault_dedupe_helperpy) script (or by other means) to the top or bottom of the vault list of 1Password.com for further assessment as potential duplicate vaults for removal. 

After you've determined that you've selected the correct vaults for deletion, you can optionally run the script again using the `--delete` flag to delete vaults. 

## Remove "Imported" prefix from imported vaults with [`remove_imported_prefix.py`](./remove_imported_prefix.py)

This script will remove the "Imported " prefix added to all vaults migrated using the LastPass importer built into the 1Password application. 

### Usage
`python3 remove_imported_prefix.py`

The script requires no arguments and has no flags or options. 

It assumes you have signed in to your 1Password account as a member of the Owners group using `op signin` or `eval $(op signin)`. 

> **warning**  
> Run this script only after you have migrated all data from LastPass and have migrated permissions for all groups and users. Removing the Imported prefix or changing the name of imported vaults in any way before you have finalized your migration may result in duplicate vaults or failure to migrate permissions. 


## Recreate the metadata vault metadata entries after a duplication occurred with [`recreate_metadata_entry.py`](./recreate_metadata_entry.py)

This script will recreate the metadata folder entries. An 'import folder permissions only' will correctly find the old vaults, rather than create empty duplicate vaults again.

### Usage

Run `python3 vault_dedupe_helper.py` to regenerate the dedup CSV.

Then run `python3 recreate_metadata_entry.py` which will create a `LastPass Metadata Recreated` item in the LastPass metadata vault.

The script requires no arguments and has no flags or options. 

It assumes you have signed in to your 1Password account as a member of the Owners group using `op signin` or `eval $(op signin)`. 

> **warning**  
> After running this script archive all other `LastPass Metadata <date>` items except for `LastPass Metadata Recreated`. This will ensure that duplication will not occur again when importing permissions.
