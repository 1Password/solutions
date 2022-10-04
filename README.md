# Examples, templates, and other goodies from the 1Password Solutions team

## Introduction
The 1Password [Command Line Interface](https://developer.1password.com/docs/cli/) (called `op` from this point forward) allows you to manage some aspects of a 1Password account, use secure secrets references to avoid storing secrets as plaintext environment variables, and perform CRUD actions on items you store in 1Password. 

This repository contains example and demo scripts for `op` with the intent of providing people with inspiration or a starting point for their own scripts. 

The scripts here assume you have the `op` [installed and configured](https://developer.1password.com/docs/cli/get-started). 

## Complete 1Password command line tool documentation
For full documentation of the 1Password command line interface, please visit [developer.1password.com/docs/cli/](https://developer.1password.com/docs/cli/) 

## Handy tools
`jq`, a command line tool with robust JSON support, is an essential tool when using `op`. Many of the provided examples use `jq` and you will need it installed before using any of the examples here. Download `jq` from [the developer](https://stedolan.github.io/jq/).

## Note
Unless otherwise stated, these scripts are not intended to be run in an automated or unattended environment.

Scripts provided here are not intended to be run as-is. They are intended as examples of how to perform certain tasks. You will need to modify the scripts to fit your exact needs and suite your specific environment. 

## Contents
* [Provision new users from a CSV](./op-cli-example-scripts/scripted-provisioning/)
* [Scripts for auditing or managing existing users](./op-cli-example-scripts/user-management/)
* [Scripts for managing your vaults and groups](./op-cli-example-scripts/account-management/)
* [Scripts for creating or updating items in bulk](./op-cli-example-scripts/item-management)
