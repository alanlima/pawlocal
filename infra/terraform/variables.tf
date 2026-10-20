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

variable "github_repository" {
  description = "GitHub owner/repository allowed to assume the frontend deployment role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/repository format."
  }
}

variable "github_owner_id" {
  description = "Immutable GitHub owner ID used in the repository's OIDC subject claim."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must be the numeric immutable GitHub owner ID."
  }
}

variable "github_repository_id" {
  description = "Immutable GitHub repository ID used in the OIDC subject claim."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be the numeric immutable GitHub repository ID."
  }
}

variable "terraform_state_bucket_name" {
  description = "Existing S3 bucket that stores the shared PawLocal Terraform root state."
  type        = string
  validation {
    condition     = length(trimspace(var.terraform_state_bucket_name)) > 0
    error_message = "terraform_state_bucket_name must name the existing Terraform state bucket."
  }
}

variable "manage_github_oidc_provider" {
  description = "Keep Terraform ownership of the GitHub OIDC provider already managed by the existing root state."
  type        = bool
  default     = true
}

variable "force_destroy_on_teardown" {
  description = "Allow an explicitly approved Terraform teardown to empty app-owned S3 buckets and remove Aurora DSQL clusters with deletion protection enabled. Leave false for normal operation."
  type        = bool
  default     = false
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
