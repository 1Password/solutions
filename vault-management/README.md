# Vault management examples

## Introduction

This folder includes example scripts for managing vaults with 1Password CLI.

## Scripted vault provisioning

### [`vault-provisioning.sh`](./vault-provisioning.sh)

Group provisioning can be automated using SCIM provisioning (see [Automate provisioning in 1Password Business using SCIM](https://support.1password.com/scim/)), but the SCIM protocol does not have any concept of vaults. This script can be used to automate vault creation.

The script creates a vault that will be shared with a 1Password group, with access by some requesting team member and an approving manager, which can be uniquely set for each.

An example use case is using a SOAR tool to request, approve, and provision a directory group along with an associated vault for a team or department. The group can be assigned to 1Password using SCIM; this script can be used alongside SCIM provisioning to create the associated vault.

This script reads the account password from `stdin`, for example:

```sh
echo $ACCOUNT_PASSWORD | ./vault-provisioning.sh
```

Other inputs can be consumed from the environment and/or supplied inline, e.g.:

```sh
echo $ACCOUNT_PASSWORD | \
    VAULT_NAME="A new vault" \
    VAULT_DESCRIPTION="A helpful description or some other reference." \
    ./vault-provisioning.sh
```

The script assumes that 1Password CLI has already been intialized on the device ahead of running the script (see [Sign in to your 1Password account manually](https://developer.1password.com/docs/cli/sign-in-manually#add-an-account)).
