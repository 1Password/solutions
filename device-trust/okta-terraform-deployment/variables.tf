variable "okta_domain" {
  type = string
  description = "Your Okta domain. Your Okta tenant address is usually something like '{YOUR_OKTA_DOMAIN}.okta.com'."
}

variable "okta_host" {
  type = string
  description = "Your Okta instance's host. For example, 'okta.com' or 'oktapreview.com'."
}