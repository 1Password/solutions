# Example apps for Marketing Launch of Complete Item Management

# General Details
* Promote newly-implemented item management-related features of the 1Password SDK. 


# Date
* April 15 Marketing launch (tier II) 

# Examples

## [Use 1Password as a backend for web app](./demo-inventory-tracker-webapp/)
#### Description
This web application allows you to create and manage "IT Resources" such as computers. 
* Create new "Devices", including their name, model, serial number, and Admin user credentials. 
    * Each device is represented by an item in 1Password. 
* Display a list of all current devices. 
* Edit or delete existing devices. 

#### Featuring
* 1Password Javascript SDK
* 1Password Service Accounts

#### Highlights
* Collect sensitive information from anyone using a web form and store that information securely in 1Password
* Display information from 1Password items on a webpage. 

#### Potential real world use-cases
* If you're a client services organization, collect sensitive information from your clients via a web portal and store it in 1Password, even if your clients aren't 1Password users. 
  * Credentials for client-owned services you manage. 
  * Credit card information for clients
* Provide limited access to information stored in 1Password, such as to employees in an internal app. 

## [Migrate data between 1Password tenants](./demo-vault-migration/)
#### Description
This web application facilitates the movement of vaults and their contents between two separate 1Password accounts. 

#### Featuring
* 1Password Javascript SDK
* 1Password CLI
* 1Password Service Accounts

#### Highlights
* Securely move data between two 1Password accounts without writing any data to disk. 
* Use 1Password SDKs to back a web front-end. 

#### Potential real world use-cases
* Consolidating 1Password information across multiple accounts during mergers, acquisitions or other organizational transitions.


## [Share files and markdown securely with Secure Item Sharing Links](./demo-share-script/)
#### Description
This Python script creates a 1Password item from files in a directory of your choice for the purposes of securely sharing source code and a README. A README.md file present in the directory becomes the markdown-formatted contents of the Notes section of a 1Password item. Other files in the directory are attached to the 1Password item. 

Finally, the script produces a Secure Item Sharing Link so you can securely share the item with the intended recipient. 

#### Featuring
* 1Password Python SDK
* 1Password Service Accounts
* File Attachments to 1Password items. 
* Item Sharing Links

#### Highlights
* Use the SDK to build bespoke command-line utilities. 
* Use the SDK to attach files to 1Password items. 

#### Potential real world use-cases
* Programmatically write or read cert or key files stored as attachments in 1Password for machine-machine authentication. 
* Share text and files securely with anyone, whether they use 1Password or not. 
* Create custom sharing utilities 

## [Secure and Streamline Employee Onboarding with Okta](./demo-create-okta-user/)
#### Description
This Python script is an example of how you can streamline and secure employee onboarding. Running this script allows you to create a new Okta user and generate a strong password for their Okta account. The script provides a Secure Item Share Link for the new Okta user's Okta credentials which can be shared with the new employee, such as through a non-work email or other means. 

#### Featuring
* Python SDK
* Secure Item Sharing Links
* Okta API

#### Highlights
* Use 1Password SDKs to interact with additional third party services. 
* Use 1Password SDKs to generate secure passwords for external services and store the information in 1Password

#### Potential real world use-cases
* Onboarding new employees, particularly when Okta is required to access email inboxes or where inboxes may not be provisioned quickly enough. 