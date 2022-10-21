# Scripted provisioning with the 1Password CLI tool
## Introduction
This script uses 1Password's Command Line Tool v2 to read names and email addresses from a file on disk and invite each person on the last to join a 1Password Business account. 

For more information about managing users with the 1Password command line tool, see the complete documentation for [op user](https://developer.1password.com/docs/cli/reference/management-commands/user).

## Account setup
Enable provisioning via the CLI on your 1Password account by visiting https://start.1password.com/settings/provisioning/cli. This will create a group called "Provisioning Manager" with a special permission (Provision People). This allows any member of that group to invite peopl using the 1Password CLI. Only the account you created for the purposes of provisioning users needs to be added to this group, but you can add others to this gorup as needed. 

## Preparations
Your input document should be a csv file. It:
* Must not include a header (an alternative command is offered in the script if you need a header)
* Must not include spaces after the comma
* Contain only two columns
* Must include a trailing empty line

For example:
```
firstName lastName,email@example.com
otherName moreName,another_email@example.com

```
### Additional considerations
* You can include as many names as a person needs (e.g., `Wendy van der Appleseed` is a valid name)
* If a name includes double quotes, this script will substitute single quotes (e.g., `Wendy "Apple" Applessed` becomes `Wendy 'Apple' Appleseed`)
* Non-latin characters (e.g., simplified Chinese) should be supported, but have not been thoroughly tested; your mileage may vary. 


## Additional options
There is an additional example at the bottom of the script. **This will irrecoverably delete the users in the input file**. This is not the recommended process for deleting users but may be useful if you are testing the script with fake users and need to quickly delete users you just invited. 