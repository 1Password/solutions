# 1Password Vault Provisioning Script

## Overview

This repository contains a PowerShell script that provisions 1Password
vaults and assigns permissions based on a CSV file.\
It uses a **1Password Service Account** for automation and includes
logic to handle rate limits safely.

## Requirements

-   Windows PowerShell 5.1 or PowerShell 7+
-   [1Password CLI
    v2](https://developer.1password.com/docs/cli/get-started) (`op`)
    installed and available in PATH
-   Environment variable `OP_SERVICE_ACCOUNT_TOKEN` set to a valid
    Service Account token

## CSV Format

The input CSV must include the following columns:

  ---------------------------------------------------------------------------------------------
  VaultName   Owner               Members                                   AdminGroup
  ----------- ------------------- ----------------------------------------- -------------------
  Vault1      owner@example.com   member1@example.com;member2@example.com   IT-Admins

  Vault2      alice@example.com   bob@example.com                           carol@example.com
  ---------------------------------------------------------------------------------------------

-   **VaultName**: Name of the vault to create or update\
-   **Owner**: A user identifier (email or user ID). Granted full
    ownership permissions\
-   **Members**: One or more user identifiers separated by `,` or `;` or
    `|`. Granted *manage, view, and copy* permissions\
-   **AdminGroup**: A group identifier (name or ID). Granted *manage*
    permission

## Usage

1.  Ensure `op` CLI is authenticated with a service account:

    ``` powershell
    $env:OP_SERVICE_ACCOUNT_TOKEN = "<your-service-account-token>"
    ```

2.  Run the script with your CSV file:

    ``` powershell
    .\Provision-Vaults.ps1 -CsvPath .\vaults.csv
    ```

3.  Use `-DryRun` to preview changes without applying:

    ``` powershell
    .\Provision-Vaults.ps1 -CsvPath .\vaults.csv -DryRun
    ```

## Rate Limiting

The script uses exponential backoff with jitter when encountering HTTP
429 or transient errors.\
It also adds a small randomized delay between vault operations.

## Example `vaults.csv`

``` csv
VaultName,Owner,Members,AdminGroup
Finance,finance.owner@example.com,analyst1@example.com;analyst2@example.com,Finance-Admins
HR,hr.owner@example.com,hrstaff1@example.com|hrstaff2@example.com,HR-Admins
Engineering,eng.owner@example.com,dev1@example.com,DevOps-Admins
```

## Dry Run

Dry run mode will print what would happen without actually creating or
modifying vaults. Use it to validate the CSV before execution.

``` powershell
.\Provision-Vaults.ps1 -CsvPath .\vaults.csv -DryRun
```
