# User management examples
## Introduction
These scripts are examples of how you can manage users with the 1Password command line tool. 

## Audit user's vault access
If you would like to know which vaults a person has access to and what their permissions are, [audit-user-vault-access.sh](audit-user-vault-access.sh) provides a basic starting point for your own ascript. 

This script requires you to provide a person's UUID, which can be obtained with 
`op user get <user's email or name>`

Note that this doesn't include vaults a person has access to by virtue of their group membership. 