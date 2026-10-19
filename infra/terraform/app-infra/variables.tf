variable "aws_region" {
  description = "AWS region for the S3 site bucket and GitHub deploy role."
  type        = string
  default     = "ap-southeast-2"
}

variable "environment" {
  description = "Environment tag applied to taggable AWS resources."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be development, staging, or production."
  }
}

variable "domain_name" {
  description = "Root DNS domain with an existing public Route 53 hosted zone, without a trailing dot."
  type        = string
}

variable "site_subdomain" {
  description = "Label prepended to domain_name for the public site hostname."
  type        = string
  default     = "pawlocal"
}

variable "certificate_arn" {
  description = "ARN of an existing ACM certificate covering the site FQDN, in us-east-1."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^arn:[^:]+:acm:us-east-1:[0-9]{12}:certificate/.+$", var.certificate_arn))
    error_message = "certificate_arn must identify an ACM certificate in us-east-1."
  }
}

variable "backend_image_digests" {
  description = "Environment-keyed immutable public GHCR image references. Development and production must use the same digest when promoting a release."
  type        = map(string)
  default     = {}
  validation {
    condition = alltrue([
      for image in values(var.backend_image_digests) : can(regex("^ghcr\\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}$", image))
    ])
    error_message = "Backend images must be public ghcr.io/alanlima/pawlocal-api references pinned to a sha256 digest."
  }
  validation {
    condition     = alltrue([for environment in keys(var.backend_image_digests) : contains(["development", "production"], environment)])
    error_message = "Backend image keys may only be development and production."
  }
}

variable "dsql_bootstrap_python" {
  description = "Absolute path to the Python interpreter with backend dependencies installed; used by Terraform's DSQL role bootstrap local-exec."
  type        = string
  validation {
    condition     = length(trimspace(var.dsql_bootstrap_python)) > 0
    error_message = "dsql_bootstrap_python must name the configured backend Python interpreter."
  }
}

variable "enable_dsql_auth_event_capture" {
  description = "Enable CloudTrail capture of DSQL DbConnect data events; this is security auditing, not application telemetry."
  type        = bool
  default     = false
}

variable "dsql_auth_audit_bucket_name" {
  description = "Owner-selected destination S3 bucket name for DSQL authentication audit events. Required when event capture is enabled."
  type        = string
  default     = null
  nullable    = true
}

variable "dsql_auth_retention_days" {
  description = "Owner-selected number of days to retain DSQL authentication audit objects. Required when event capture is enabled."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.dsql_auth_retention_days == null ? true : (var.dsql_auth_retention_days > 0 && floor(var.dsql_auth_retention_days) == var.dsql_auth_retention_days)
    error_message = "When specified, dsql_auth_retention_days must be a positive whole number of days."
  }
}

variable "dsql_auth_alert_email" {
  description = "Optional owner-selected email recipient for DSQL authentication event alerts. SNS requires recipient confirmation."
  type        = string
  default     = null
}
