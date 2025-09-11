##### SAML APPLICATION #####

resource "okta_app_saml" "device_trust_kolide" {
    label                 = "Device Trust"
    saml_version          = "2.0"
    status                = "ACTIVE"
    hide_ios              = false
    hide_web              = false
    logo                  = "./kolide-logo.png"

    # TODO: Paste Kolide ACS URL to 'sso_url', 'recipient', and 'destination'.
    sso_url     = "https://app.kolide.com/5213/saml/ce496209-b7bf-408b-8e86-683a947c46af/consume"
    recipient   = "https://app.kolide.com/5213/saml/ce496209-b7bf-408b-8e86-683a947c46af/consume"
    destination = "https://app.kolide.com/5213/saml/ce496209-b7bf-408b-8e86-683a947c46af/consume"
    
    # TODO: Paste Kolide Entity ID to 'audience'.
    audience    = "https://app.kolide.com/5213/saml/ce496209-b7bf-408b-8e86-683a947c46af/metadata"

    authn_context_class_ref  = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
    subject_name_id_format   = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
    
    # TODO (Optional): Change if you want to map another field.
    subject_name_id_template = "$${user.userName}"

    signature_algorithm = "RSA_SHA256"
    digest_algorithm    = "SHA256"
    response_signed     = true
    assertion_signed    = true
    honor_force_authn = true

}


##### GROUP ASSIGNMENT #####

resource "okta_group" "dt_enabled_group" {
    name        = "Device Trust Enabled"
    description = "Group for testing Terraform Okta deployment"
}

resource "okta_app_group_assignment" "dt_group_assignment" {
    app_id   = okta_app_saml.device_trust_kolide.id
    group_id = okta_group.dt_enabled_group.id
}


##### Identity Provider #####

resource "okta_idp_saml_key" "dt_idp_key" {
  x5c = [tostring(file("./kolide_idp_signature_certificate.pem"))]
}

resource "okta_idp_saml" "dt_idp" {
    # This name will be visible to the end-users during the authentication flow
    name            = "Device Trust"
    sso_url         = "https://auth.kolide.com/saml"
    issuer          = "https://auth.kolide.com/saml"
    sso_destination = "https://auth.kolide.com/saml"
    kid             = okta_idp_saml_key.dt_idp_key.id
    max_clock_skew = 120000
    honor_persistent_name_id = true
}


##### AUTHENTICATOR #####

# (issue) This may not create an authenticator. If that's the case, create an authenticator manually and proceed.
# You will still need this code block since it's referenced in policies.
resource "okta_authenticator" "dt_authenticator" {
    name = "Device Trust"
    key  = "external_idp"
    legacy_ignore_name = false

    settings = jsonencode({
        "provider" : {
        "type" : "CLAIMS",
        "configuration" : {
            "idpId" : okta_idp_saml.dt_idp.id
        }
        }
    })

    depends_on = [okta_idp_saml.dt_idp]
}


##### AUTHENTICATOR ENROLLMENT POLICY #####

resource "okta_policy_mfa" "dt_mfa" {
    name        = "Device Trust Enrollment"
    description = "Requires users in the security group to enroll with 1Password Device Trust (Kolide) factor."
    status      = "ACTIVE"
    priority    = 1
    is_oie      = true

    okta_password = {
        enroll = "REQUIRED"
    }

    # (Optional) You can set 'enroll' to 'OPTIONAL' or 'REQUIRED'.
    external_idps = [
        {
            "id"     = okta_authenticator.dt_authenticator.id,
            "enroll" = "REQUIRED",
        }
    ]

    groups_included = [
        okta_group.dt_enabled_group.id,
    ]
}

resource "okta_policy_rule_mfa" "dt_mfa_rule" {
  policy_id = okta_policy_mfa.dt_mfa.id
  name      = "Default"
  priority  = 1
  status    = "ACTIVE"
}


##### AUTHENTICATION POLICY #####

data "okta_app_signon_policy" "dt_auth_policy" {
    app_id = okta_app_saml.device_trust_kolide.id
}

# TODO (Optional): Build an authentication method chain as you wish.
# This example uses 2FA with password and Device Trust.
# Check the documentation for details on the keys and methods of the authenticationMethod object.: https://github.com/okta/okta-developer-docs/blob/349f9e1ada9d4c8b95f608ac21a64d524cbb7c02/packages/%40okta/vuepress-site/docs/concepts/mfa/index.md?plain=1#L85
resource "okta_app_signon_policy_rule" "dt_auth_policy_rule" {
    access                      = "ALLOW"
    groups_included             = [okta_group.dt_enabled_group.id]
    inactivity_period           = "PT1H"
    name                        = "Device Trust Protected"
    policy_id                   = data.okta_app_signon_policy.dt_auth_policy.id
    priority                    = 0
    re_authentication_frequency = "PT0S"
    type                        = "AUTH_METHOD_CHAIN"
    chains = [jsonencode(
        {
        "authenticationMethods" : [
            {
            "key" : "okta_password",
            "method" : "password"
            }
        ],
        "next" : [{
            "authenticationMethods" : [{
                "key" : "external_idp"
                "method" : "idp",
                "id" : okta_authenticator.dt_authenticator.id,
            }]
        }]
        }
    )]
}


##### OUTPUT #####

output "kolide_instructions" {
    value = {
        set_up_single_sign-on = {
            description = "Enter the following information within Device Trust - Set Up Single Sign-On"
            sso_url     = okta_app_saml.device_trust_kolide.http_post_binding
            certificate = okta_app_saml.device_trust_kolide.certificate
            metadata_url_for_cert = okta_app_saml.device_trust_kolide.metadata_url
        }
        device_trust_authenticator = {
            description = "Enter the following information within Device Trust - Device Trust Authenticator"
            idp_id = okta_idp_saml.dt_idp.id
            acs_url = "https://${var.okta_domain}.${var.okta_host}/sso/saml2/${okta_idp_saml.dt_idp.id}"
            audience_uri = okta_idp_saml.dt_idp.audience
            certificate_link = "${var.okta_domain}-admin.${var.okta_host}/admin/access/identity-providers"
        }
    }
}