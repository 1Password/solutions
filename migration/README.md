# Migration tools

This section contains scripts to assist with migrating or importing data into 1Password.

If you are migrating from another password management system, please visit <https://support.1password.com/import/> to learn more about your options.

If you are migrating from LastPass, read more about our LastPass importer here: <https://support.1password.com/import-lastpass/>

## Contents

### [/cleanup-scripts](./cleanup-scripts/)
This directory contains several scripts to help people identify or clean up certain things after performing a migration from another password manager. Currently the scripts target certain tasks that LastPass migrators may encounter. 

* `vault_dedupe_helper.py` generates a csv-like report containing a list of all shared vaults you have access to, along with metadata about each vault. If, after migrating, you ended up with some duplicate vaults, this report might help you identify which duplicates to delte, and which one to retain
* `add_vault_prefix.py` acts on a list of vault UUIDs. By default, it will prefix each vault name with `!` to make it easier to sort and further assess potential duplicates. This script can optionally be run in Delete Mode, which will delete the vault. 

### [/lastpass](./lastpass/)
This directory contains a script that offers a variety of ways to import data from LastPass to 1Password. 

We strongly encourage you to use the LastPass import too included with 1Password for macOS, Windows, and Linux. If you are migrating from LastPass, read more about our LastPass importer here: <https://support.1password.com/import-lastpass/>

However, this script may be helpful in certain scenarios, or as a demonstration of the capabilities of the [1Password CLI](https://developer.1password.com/docs/cli).