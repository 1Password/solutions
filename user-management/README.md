# User management examples

## Introduction

These scripts are examples of how you can manage users with the 1Password command line tool.

## Audit user's vault access

If you would like to know which vaults a person has access to and what their permissions are, [audit-user-vault-access.sh](audit-user-vault-access.sh) provides a basic starting point for your own ascript.

This script requires you to provide a person's UUID, which can be obtained with `op user get <user's email or name>`

Note that this doesn't include vaults a person has access to by virtue of their group membership.

## Identify Abentees

The [identify-abenstees.sh](identify-absentees.sh) script will prompt you for a number of days (N) after which you consider a user to not be adequately engaged (or "absent") from 1Password. It will then create a list of users who have not authenticated into 1Password for N days or longer. You can use this list to reach out to disengaged users or as input for other scripts to perform bulk actions on those users.

This script also provides some suggestions for modifying it's output depending on your needs.
