# LastPass Migration Cleanup Scripts

This is a collection of scripts that can help you clean up your 1Password account after performing a migration from LastPass. 

## [vault_dedupe_helper.py](./vault_dedupe_helper.py)

This script will create a csv-like report intended to help you identify duplicate vaults that may have been created under certain circumstances when multiple members of your 1Password account used the LastPass importer. 

The generated report will list each vault in your account, with rows for:
```
vault name, vault UUID, item count, vault creation date, vault updated, number of users
```

> **Warning**
>
> This script should be run by a member of the Owners group of your 1Password account. 


### [add_vault_prefix.py](./add_vault_prefix.py)
