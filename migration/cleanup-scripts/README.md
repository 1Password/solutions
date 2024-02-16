# LastPass Migration Cleanup Scripts

This is a collection of scripts that can help you clean up your 1Password account after performing a migration from LastPass. 

> ⚠️ **Warning**  
> Currently, you must use version 2.21 or older of the 1Password CLI when running these scripts. Version 2.22 and newer introduced changes that prevent these scripts from performing as-expected. Download version 2.21 the 1Password website [here](https://app-updates.agilebits.com/product_history/CLI2#v2210002).

## Contents

* [`vault_dedupe_helper.py`](#identify-duplicate-vaults-for-removal-with-vault_dedupe_helperpy) generates a report for all shared vaults in your account that can help you identify which duplicates to delete, and which to retain. 
* [`add_vault_prefix.py`](#further-investigate-or-delete-potential-duplicate-vaults-with-add_vault_prefixpy) can take a list of vault UUIDs and prefix each vault name with `!` to make them easy to identify in 1Password for further assessment. Alternatively using the `--delete` option will delete each vault provided in the list. 
* [`remove_imported_prefix.py`](#remove-imported-prefix-from-imported-vaults-with-remove_imported_prefixpy) will remove the "Imported " prefix from the name of all vaults in your 1Password account. Handy to clean things up once you have finalized your migration. 
* [`recreate_metadata_entry.py`](#recreate-metadata-entry) will reconstruct the metadata entries in the metadata vault to point to the oldest imported vaults

> **note**  
> Learn more about migrating your data from LastPass to 1Password [here](https://support.1password.com/import-lastpass/).  

## Generate a list of vault names and UUIDs with [`vault_name_id_list.py`](./vault_name_id_list.py)
This is a lightweight script that will generate a csv containing two columns: `vaultName` and `vaultUUID`. Each row represents a vault that the person running the script has access to. 

This script must be run by a member of the Owners group and must be run with v2.21 or older of the `op` cli. 

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

This script will recreate the metadata folder entries. Once recreated, using the LastPass importer in the 1Password desktop application with 'import folder permissions only' selected will correctly find the old vaults, rather than create empty duplicate vaults again.

### Usage

Run `python3 vault_dedupe_helper.py` to regenerate the dedup CSV.

Then run `python3 recreate_metadata_entry.py` which will create a `LastPass Metadata Recreated` item in the LastPass metadata vault.

The script requires no arguments and has no flags or options. 

It assumes you have signed in to your 1Password account as a member of the Owners group using `op signin` or `eval $(op signin)`. 

> **warning**  
> After running this script archive all other `LastPass Metadata <date>` items except for `LastPass Metadata Recreated`. This will ensure that duplication will not occur again when importing permissions.


## Move items from untracked vault to tracked vault with [`move_items_to_tracked_vault.py`](./move_items_to_tracked_vault.py)

This script should only be used if you are very sure you need to use it. Before you run this script, please reach out to your primary contact at 1Password or [1Password Support](https://support.1password.com/contact/) to determine if this script will be helpful. 

### When to use this script

This script is intended to remediate the following scenario in a 1Password Business account:
* Data was migrated from LastPass to 1Password using the LastPass imported in 1Password 8. 
* The import was subsequently run using the "Import Permissions Only" setting enabled. 
* Duplicate vaults with no data, but updated permissions, were created in 1Password. 

Use this script with caution. This script makes some assumptions that may or may not be true, and which may be hard to verify:
* That a vault containing data are no longer tracked by the "❗️ LastPass Imported Shared Folders Metadata" vault. 
* That a vault of the same name as the first, but which has updated permissions and contains no data, is tracked by the "❗️ LastPass Imported Shared Folders Metadata". 

Typically, this scenario arises if the "❗️ LastPass Imported Shared Folders Metadata" vault was manually changed by someone after the initial import and is no longer able to track the vaults that contain the imported data. Subsequent use of the importer would result in the creation of duplicate vaults (since the originals are no longer tracked by "❗️ LastPass Imported Shared Folders Metadata"), but contain no data (because the mechanism used to prevent duplicate data are still in place in LastPass and the data is ignored).  

### What the script does
This script performs the following actions:
* Identifies vaults that have identical names and assembles them into groupings. 
    * The script ignores the "❗️ LastPass Imported Shared Folders Metadata" vault and Private vaults. 
* For each grouping, the script:
    * Identifies the vault in the set with the largest number of items. This is considered the "Data vault" containing the correct items. 
    * Identifies the vault in the set with zero items. This is considered the "Tracked vault" that the "❗️ LastPass Imported Shared Folders Metadata" is tracking. 
    * If there are more than two identically-named vaults in the set, they are considered "other vaults".
* The Owners group is granted full permission on each vault in the grouping so it can perform the subsequent parts of this script. 
* All items are moved from the "Data vault" to the "Tracked vault". Data in "other vaults" is ignored. 
* The Data and Other vaults are renamed to add `dup-` as a prefix and a numeric suffix. 
* All users and groups have their access and all permissions revoked from Data and Other vaults 

### Expected outcome
The intended outcome is:

* All migrated data is in vaults the "❗️ LastPass Imported Shared Folders Metadata" is tracking. 
* All duplicate vaults not tracked by "❗️ LastPass Imported Shared Folders Metadata" are no longer accessible to end-users and named for easy review and deletion at a future date. 
* Subsequent use of the LastPass importer with "Import Permissions Only" enabled should update permissions on the vaults into which the data was moved and which should be tracked by "❗️ LastPass Imported Shared Folders Metadata". In theory, no additional duplicates should be created. 

### Usage

Run `python3 move_items_to_tracked_vault.py` to execute the script. This script will take a long time to run. 

It assumes you have signed in to your 1Password account as a member of the Owners group using `op signin` or `eval $(op signin)`. 

The script requires no arguments and has no flags or options. 

