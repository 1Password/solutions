terraform {
  required_providers {
    okta = {
      source = "okta/okta"
    }
  }
}

provider "okta" {
    org_name = "1password5"
    base_url = "oktapreview.com"
    client_id   = "0oaplld2jpVIBZPDS1d7"
    scopes = [
        "okta.apps.manage",
        "okta.authenticators.manage",
        "okta.groups.manage",
        "okta.policies.manage",
        "okta.idps.manage",
        "okta.profileMappings.read",
        ]
    private_key = "./okta_api.key"
}
