# Device Trust Okta Terraform Deployment

## Introduction
If your organization uses Terraform to manage its Okta instance, you can use this example to create Device Trust related resources. This is only a sample Terraform deployment and should be tailored to your organization's specific needs.

## Instructions
1. Set up the following to get started:
    - Ensure you have the following resources in your working directory:
        - `kolide_idp_signature_certificate.pem` : This is not tenant specific, meaning you can use the certificate included in this repository. Make sure the cert **does not** include the lines `-----***BEGIN CERTIFICATE***-----` and `-----END ***CERTIFICATE***-----` in the beginning and at the end of the certificate.
        - `kolide-logo.png`
    - Edit the `devicetrust.tf` file to match your tenant configuration. The sections you need to update are marked with `TODO` .
    - Make sure your Okta instance is connected to Terraform and has the right API scopes granted.
        - If you haven't yet, follow this [Okta documentation](https://developer.okta.com/docs/guides/terraform-enable-org-access/main/) to enable Terraform access for your Okta tenant.
        - The Okta Terraform application must have the following scopes granted. These are usually defined in the [main.tf](http://main.tf) file and must also be granted in the Okta Admin Console.
        
        ```
        "okta.apps.manage",
        "okta.authenticators.manage",
        "okta.groups.manage",
        "okta.policies.manage",
        "okta.idps.manage",
        "okta.profileMappings.read",
        ```
        
2. *(Terraform)* In `devicetrust.tf` , copy the code blocks under `SAML APPLICATION` , `GROUP ASSIGNMENT` and `IDENTITY PROVIDER`, complete TODOs, and deploy. This will
    - Create a SAML application.
    - Create a test user group.
    - Assign the test user group to the SAML application.
    - Create an Identity Provider.

3. *(Manual)* In the Okta Admin Console, go to Security > Identity Providers, locate the newly created Identity Provider, click on Actions > Configure Identity Provider, and set `IdP Usage` to `Factor Only`. 
    > This is set to `SSO Only` by default.

4. *(Manual)* In the Okta Admin Console, go to Security > Authenticators and create an IdP Authenticator.
    > In some cases, the Authenticator may not appear even though no error is shown after Terraform deployment, and logs may indicate it was created. You can skip this step and continue with step 5, then return here only if an issue occurs.

5. *(Terraform)* In `devicetrust.tf` , copy the code blocks under `AUTHENTICATOR`,  `AUTHENTICATOR ENROLLMENT POLICY` , `AUTHENTICATION POLICY` and `OUTPUT`, then deploy. This will
    - Create an authenticator enrollment policy.
    - Create an authentication policy rule (applied to the policy that includes the Device Trust app).
    - Output values required to finish up Device Trust configuration inside Kolide.

6. *(Manual)* Double-check that your IdP Authenticator has **not** been unintentionally added to
    - Security > Authenticators > Enrollment policies (especially the Default Policy)
    - Security > Authentication Policies (especially Catch-all rules inside each policy)

7. *(Manual)* In Device Trust > Identity Providers, use the Terraform output `kolide_instructions.set_up_single_sign-on` of Terraform to fill in information for step ‘Single Sign-On Provider’.

8. *(Manual)* Configure SCIM provisioning inside the SAML application in Okta using information in Device Trust > Identity Providers > Set Up User Provisioning.

9. *(Manual)* In Device Trust > Identity Providers, use the Terraform output `kolide_instructions.device_trust_authenticator` to complete the ‘Set Up Authenticator’ step.
    > Be careful when pasting the certificate. Ensure there are no extra spaces and that the certificate includes `-----***BEGIN CERTIFICATE***-----` and `-----END ***CERTIFICATE***-----` at the beginning and the end of the certificate.
