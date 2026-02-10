terraform {
  required_providers {
    okta = {
      source = "okta/okta"
      version = "~> 5.0.0"
    }
    onepassword = {
      source  = "1Password/onepassword"
      version = "~> 2.1.2"
    }
  }
}

# TODO: Set this up by following this doc: https://developer.1password.com/docs/terraform/
provider "onepassword" {

}

# TODO: Put in the UUID of the vault and the item of your Okta private key item
data "onepassword_item" "okta_key" {
  vault = "vault_uuid_that_has_your_okta_key"
  uuid  = "item_uuid_that_has_your_okta_key"
}

provider "okta" {
    org_name = var.okta_domain
    base_url = var.okta_host
    client_id   = data.onepassword_item.okta_key.section.0.field.0.value
    scopes = [
        "okta.apps.manage",
        "okta.authenticators.manage",
        "okta.groups.manage",
        "okta.policies.manage",
        "okta.idps.manage",
        "okta.profileMappings.read",
        ]
    private_key = data.onepassword_item.okta_key.file.0.content
}
