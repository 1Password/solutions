# 1Password SDK Examples

Securely automate your workflows with SDKs from 1Password. 

# Introduction
Here you will find example scripts and apps leveraging 1Password's SDKs addressing a variety of use-cases. 

These examples are not intended to be used for production purposes. They are intended to demonstrate the capabilities of the SDK, highlight specific use-cases, and provide basic guidance for how to accomplish certain tasks with the SDKs. 

# Get started
* Learn more about 1Password's SDKs [here](https://developer.1password.com/docs/sdks)
* Follow the Getting Started documentation [here](https://developer.1password.com/docs/sdks/setup-tutorial)

# Security Note
* Most of these demo applications and scripts require the use of Service Account tokens and other secrets. Store all secrets securely, like in 1Password.
* These example will make changes to data in 1Password. Do not use these examples with production or other real world data. 

# Examples

## [Use 1Password as a backend for web app](./demo-inventory-tracker-webapp/)  
By: Scott Lougheed  
#### Description
This web application allows you to create and manage "IT Resources," such as computers.
* Create new "Devices", including their name, model, serial number, and Admin user credentials. 
    * Each device is represented by an item in 1Password. 
* Display a list of all current devices. 
* Edit or delete existing devices. 

#### Featuring
* 1Password Javascript SDK
* 1Password Service Accounts
* 1Password Secret References
* 1Password CLI (`op run`)

#### Highlights
* Collect sensitive information from anyone using a web form and store that information securely in 1Password.
* Display information from 1Password items on a webpage. 

#### Potential real world use cases
* If you're a client services organization, collect sensitive information from your clients using a web portal and store it in 1Password, even if your clients aren't 1Password users. 
  * Credentials for client-owned services you manage. 
  * Credit card information for clients.
* Provide limited access to information stored in 1Password, such as to employees in an internal app. 

## [Migrate data between 1Password tenants](./demo-vault-migration-webapp/)  
By: Ron Doucette  

#### Description
This web application facilitates the movement of vaults and their contents between two separate 1Password accounts. 

#### Featuring
* 1Password Javascript SDK
* 1Password CLI
* 1Password Service Accounts

#### Highlights
* Securely move data between two 1Password accounts without writing any data to disk. 
* Use 1Password SDKs to back a web front-end. 

#### Potential real world use cases
* Consolidating 1Password information across multiple accounts during mergers, acquisitions, or other organizational transitions.


## [Share files and markdown securely with Secure Item Sharing Links](./demo-share-script/)  
By: Amanda Crawley
#### Description
This Python script creates a 1Password item from files in a directory of your choice for the purposes of securely sharing source code and a README.

* A `README.md` file present in the directory becomes the markdown-formatted contents of the Notes section in a 1Password item. 
* Other files in the directory are attached to the 1Password item.

Finally, the script produces a Secure Item Sharing Link so you can securely share the item with the intended recipient. 

#### Featuring
* 1Password Python SDK
* 1Password Service Accounts
* File attachments to 1Password items. 
* Item sharing links

#### Highlights
* Use the SDK to build bespoke command-line utilities. 
* Use the SDK to attach files to 1Password items. 

#### Potential real world use-cases
* Programmatically write or read cert or key files stored as attachments in 1Password for machine-to-machine authentication.
* Share text and files securely with anyone, whether they use 1Password or not. 
* Create custom sharing utilities.

## [Secure and streamline employee onboarding with Okta](./demo-share-okta-user-script/)  
By: Amanda Crawley
#### Description
This Python script is an example of how you can streamline and secure employee onboarding. The script allows you to:

* Create a new Okta user and generate a strong password for their Okta account.
* Get a Secure Item Sharing Link for the new user's Okta credentials in 1Password. This link can be shared with the new employee, like by sending it to their personal email address.  

#### Featuring
* Python SDK
* Secure Item Sharing Links
* Okta API

#### Highlights
* Use 1Password SDKs to interact with additional third party services. 
* Use 1Password SDKs to generate secure passwords for external services and store the information in 1Password.
* Share 1Password items securely with anyone, whether they use 1Password or not.


#### Potential real world use-cases
* Onboarding new employees, particularly when Okta is required to access email inboxes or where inboxes may not be provisioned quickly enough. 