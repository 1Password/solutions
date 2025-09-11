# Device Trust Okta Terraform Deployment

## Introduction
If your organization uses Terraform to manage Okta instance, you can use this Terraform example to create Device Trust related resources. This is only an example Terraform deployment and should be tailored to your organization's needs.

## Instructions
1. Set up the following to get started.
    - Make sure you have the following resources in the same directory.
        - `kolide_idp_signature_certificate.pem` : This is not tenant specific, meaning you can use the certificate in this repository. Make sure the cert doesn’t include `-----***BEGIN CERTIFICATE***-----` and `-----END ***CERTIFICATE***-----` in the beginning and at the end.
        - `kolide-logo.png`
    - Edit `devicetrust.tf` file specific to your tenant. The parts you have to fill in are commented as `TODO` .
    - Make sure your Okta Terraform application has the following scopes granted. This is usually defined in [main.tf](http://main.tf) file as scopes, and inside the Okta application > Okta API Scopes.
        
        ```
        "okta.apps.manage",
        "okta.authenticators.manage",
        "okta.groups.manage",
        "okta.policies.manage",
        "okta.idps.manage",
        "okta.profileMappings.read",
        ```
        
2. *(Terraform)* Inside `devicetrust.tf` , copy the codes under `SAML APPLICATION` , `Group Assignment` and `Identity Provider` , complete TODOs, and deploy. This will
    - Create a SAML application.
    - Create a test user group.
    - Assign the test user group to the SAML application.
    - Create an Identity Provider.

3. *(Manual)* Inside Okta, go to Security > Identity Provider that was created, click on Actions > Configure Identity Provider, and set `IdP Usage` to `Factor Only`. (This would have been set to `SSO Only` by default.)

4. *(Manual)* Inside Okta, go to Security > Authenticator and create an IdP Authenticator.
    > We have seen cases where an Authenticator was not created even though no error was shown after deploying Terraform and the logs show that the Authenticator was created. You can skip this step and create an authenticator using Terraform (step 5), and then come back if an error occurs.

5. *(Terraform)* Inside `devicetrust.tf` , copy the codes under `AUTHENTICATOR`,  `AUTHENTICATOR ENROLLMENT POLICY` , `AUTHENTICATION POLICY` and `OUTPUT` , and deploy. This will
    - Create an authenticator enrollment policy.
    - Create an authentication policy rule. (It will be applied to the policy that has Device Trust app in it.)
    - Output information you need to put inside Device Trust.

6. *(Manual)* Make sure your IdP Authenticator didn’t sneak into any of your
    - Security > Authenticators > Enrollment policies (especially the Default Policy)
    - Security > Authentication Policies (especially Catch-all rules inside each policy)

7. *(Manual)* Inside Device Trust > Identity Providers, use the output (`kolide_instructions.set_up_single_sign-on`) of Terraform to fill in information for step ‘Single Sign-On Provider’.

8. *(Manual)* Configure SCIM provisioning inside the SAML application in Okta using information in Device Trust > Identity Providers > Set Up User Provisioning.

9. *(Manual)* Inside Device Trust > Identity Providers, use the output (`kolide_instructions.device_trust_authenticator`) of Terraform to fill in information for step ‘Set Up Authenticator’.
    > Be careful when pasting in the cert. There may be spaces, and make sure you have `-----***BEGIN CERTIFICATE***-----` and `-----END ***CERTIFICATE***-----` at the beginning and the end.
