variable "aws_region" {
  description = "Region for PawLocal application resources and Aurora DSQL."
  type        = string
  default     = "ap-southeast-2"
}

variable "root_domain" {
  description = "Existing public Route 53 hosted-zone name, without a trailing dot."
  type        = string
}

variable "cloudfront_certificate_arn" {
  description = "Existing ACM certificate ARN in us-east-1 covering pawlocal-dev and pawlocal hostnames."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^arn:[^:]+:acm:us-east-1:[0-9]{12}:certificate/.+$", var.cloudfront_certificate_arn))
    error_message = "CloudFront certificates must be issued in us-east-1."
  }
}

variable "github_repository" {
  description = "GitHub repository in owner/name format."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use owner/repository format."
  }
}

variable "github_owner_id" {
  description = "Immutable numeric GitHub owner ID for OIDC trust."
  type        = string
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID for OIDC trust."
  type        = string
}

variable "manage_github_oidc_provider" {
  description = "Create the account-level GitHub OIDC provider only if none exists."
  type        = bool
  default     = false
}

variable "deploy_ssh_public_keys" {
  description = "Environment-keyed SSH public keys for GitHub deployment users. Private keys are supplied independently as GitHub environment secrets."
  type        = map(string)
  sensitive   = true
  validation {
    condition     = alltrue([for k in keys(var.deploy_ssh_public_keys) : contains(["development", "production"], k)])
    error_message = "Keys may only be development and production."
  }
}

variable "ssh_cidr_blocks" {
  description = "IPv4 CIDRs allowed to SSH to each Lightsail instance. Do not use 0.0.0.0/0."
  type        = list(string)
  validation {
    condition     = length(var.ssh_cidr_blocks) > 0 && alltrue([for cidr in var.ssh_cidr_blocks : cidr != "0.0.0.0/0"])
    error_message = "Provide at least one restricted IPv4 CIDR; unrestricted SSH is rejected."
  }
}

variable "enable_dsql_auth_event_capture" {
  description = "Capture DSQL DbConnect data events in a dedicated CloudTrail trail. Adds metered data-event and storage charges; this is security audit logging, not application telemetry."
  type        = bool
  default     = true
}

variable "dsql_auth_alert_email" {
  description = "Optional email for DSQL authentication-event notifications. SNS requires confirmation by the recipient."
  type        = string
  default     = null
}

variable "environment_sizes" {
  description = "Lightsail plans per environment. Defaults match the $7 development plus $12 production pricing scenario; sizes require post-deploy load review."
  type = map(object({
    bundle_id     = string
    hostname      = string
    api_name      = string
    database_role = string
  }))
  default = {
    development = { bundle_id = "small_3_0", hostname = "pawlocal-dev", api_name = "api-dev", database_role = "pawlocal_development_app" }
    production  = { bundle_id = "medium_3_0", hostname = "pawlocal", api_name = "api", database_role = "pawlocal_production_app" }
  }
}
