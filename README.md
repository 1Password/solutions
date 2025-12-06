# Examples, templates, and other goodies from the 1Password Solutions team

<h2><center>✨ News! </center></h2>
Introducing new item management with 1Password SDKs! 

* [Read all about the 1Password SDKs](https://developer.1password.com/docs/sdks/)
* [Check out a demo app or script](/onepassword_sdks/)

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

* ✨ **NEW!** [Use 1Password SDKs to perform bulk actions](1password/onepassword_sdks/)
* [Migrate from another password solution](1password/migration/)
* [Provision new users from a CSV](1password/scripted-provisioning/)
* [Scripts for auditing or managing existing users](1password/user-management/)
* [Scripts for managing your vaults and groups](1password/account-management/)
* [Scripts for creating or updating items in bulk, as well as item-sharing](1password/item-management)
