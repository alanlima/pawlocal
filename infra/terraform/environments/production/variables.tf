variable "aws_region" { type = string }
variable "root_domain" { type = string }
variable "route53_zone_id" { type = string }
variable "cloudfront_certificate_arn" {
  type      = string
  sensitive = true
}
variable "runtime_role_arn" {
  type    = string
  default = ""
}
variable "cognito_pre_sign_up_role_arn" {
  description = "Exact bootstrap-owned production Cognito pre sign-up Lambda execution role ARN."
  type        = string
  validation {
    condition     = can(regex("^arn:[^:]+:iam::[0-9]{12}:role/pawlocal-production-cognito-pre-signup$", var.cognito_pre_sign_up_role_arn))
    error_message = "cognito_pre_sign_up_role_arn must be the production Cognito pre sign-up role ARN."
  }
}
variable "backend_image" {
  type    = string
  default = ""
}
variable "cloudfront_distribution_arn" {
  type    = string
  default = ""
}
variable "cloudfront_oac_arn" {
  type    = string
  default = ""
}
variable "teardown_enabled" {
  description = "Protected destroy preparation switch. Ordinary production operations must leave this false."
  type        = bool
  default     = false
}
