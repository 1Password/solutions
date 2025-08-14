# 1Password Vault Items Importer

This PowerShell script automates the process of importing login items into 1Password vaults using the 1Password CLI and a pre-configured service account token (optional).

## 🛠 Prerequisites

- **1Password CLI (`op`)** installed and available in your environment.
- **Service account token** already configured for CLI authentication.
- **CSV input file** formatted as follows:

```csv
Vault_Name,Login_Name,Vault_Item_Password_Name,Vault_Item_Uname,Vault_Item_Pass,Vault_Item_WebSite
```

Each row represents a login item with:
- `Vault_Name`: Target 1Password vault
- `Vault_Item_Password_Name`: Item title
- `Vault_Item_Uname`: Username
- `Vault_Item_Pass`: Password
- `Vault_Item_WebSite`: Website URL

## 📄 Script Parameters

- `CsvPath` (default: `.\import-items.csv`)  
  Path to the CSV file containing the items to import.

- `ServiceAccountToken`  
  The service account token used for authentication with the `op` CLI.

## ▶️ Usage

```powershell
.\import-items.ps1 -CsvPath "path\to\your\file.csv" -ServiceAccountToken "your_token_here"
```

## 🧾 Output

- Items are created in the specified vaults using the `op item create` command.
- Logging is written to `import-log-DATE.txt` in the current directory.
  - Successful imports: `Created item 'title' in vault 'vault_name'`
  - Failures: `Failed to create item 'title' in vault 'vault_name'`

## 📌 Notes

- This script does not validate field values—ensure your CSV is well-formed.
- Errors encountered during item creation are logged; check the console and log file for details.