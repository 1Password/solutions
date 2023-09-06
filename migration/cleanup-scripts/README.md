# LastPass Migration Cleanup Scripts

This is a collection of scripts that can help you clean up your 1Password account after performing a migration from LastPass. 

* [vault_dedupe_helper.py](#identify-duplicate-vaults-for-removal-with-vault_dedupe_helperpy) generates a report for all shared vaults in your account that can help you identify which duplicates to delete, and which to retain. 
* [add_vault_prefix.py](#further-investigate-or-delete-potential-duplicate-vaults-with-add_vault_prefixpy) can take a list of vault UUIDs and prefix each vault name with `!` to make them easy to identify in 1Password for further assessment. Alternatively using the `-r` will delete each vault provided in the list. 

## Identify duplicate vaults for removal with [vault_dedupe_helper.py](./vault_dedupe_helper.py)

This script will create a csv-like report intended to help you identify duplicate vaults that may have been created under certain circumstances when multiple members of your 1Password account used the LastPass importer. The generated report will be created in the same directory as the script. 

#### Usage
`python3 vault_dedupe_helper.py`

The script has no options and requires no input. 

The generated report will list all shared vault in your account, with columns for:
```
vault name, vault UUID, item count, vault creation date, vault updated, number of users
```

With this information, you can determine which duplicate may be worth retaining, and which can be deleted. 

For example, among a set of identically-named vaults, you might keep the one that has a slightly different number of items, and which more than one person has access to. These might suggest that this vault, and not the other duplicates, is the one currently being used. 

There may be other criteria that you can use to determine which duplicates should be removed. 

> **Warning**
>
> This script should be run by a member of the Owners group of your 1Password account. 

Once you have identified canadidates for removmal, you can copy the UUIDs of those vaults into a separate file containing only a list of linebreak-delimited vault UUIDS for further processing, such as by the [add_vault_prefix.py](#add_vault_prefixpy) script, or a script of your own. That list should be formatted as:

```
wupizr5o5z4vrehdjsaaicr2cu
mvdcqrmfg7a7osxjz5lu76fyra
n7gh6luc2x53losrps2rgjx65a
evorxmphuygomvsuwdroo2nnq4
hz7dmac3lgs6pvc2qsolgcpqhu
ieeogr3drcxght5jk2fyhip7pa
gameqe75bm5l34uqk5j5enuipa
```

### Further investigate or delete potential duplicate vaults with [add_vault_prefix.py](./add_vault_prefix.py)
This script will apply `!` as a prefix to all vaults provided as a list of vault UUIDs to the script. The script requires the `--file` flag, which must point to a file containing a linebreak-deliminted list of vault UUIDs.

#### Usage

`python3 add_vault_prefix.py --file=path/to/vaultList [OPTIONS]`

`--file` should be a path to a file containing a list of vault UUIDs (and nothing else)

`-r` runs the script in Delete Mode, deleting all vaults in the provided list. 

> **warning**
> 
> Deleting vaults is _irreversible_. Be extremely careful running this script in Delete Mode. You may want to run the script in default mode to ensure that you have selected the correct vault candidates for deletion.  

#### Format for vault list file
The script expects a file containinga list of vault UUIDs formatted in this way:
```
wupizr5o5z4vrehdjsaaicr2cu
mvdcqrmfg7a7osxjz5lu76fyra
n7gh6luc2x53losrps2rgjx65a
evorxmphuygomvsuwdroo2nnq4
hz7dmac3lgs6pvc2qsolgcpqhu
ieeogr3drcxght5jk2fyhip7pa
gameqe75bm5l34uqk5j5enuipa
```

This allows you to easily sort all vaults identified using the [vault_dedupe_helper.py](#vault_dedupe_helperpy) script (or by other means) to the top or bottom of the vault list of 1Password.com for further assessment as potential duplicate vaults for removal. 

After you've determined that you've selected the correct vaults for deletion, you can optionally run the script again using the `-r` flag to delete vaults. 
