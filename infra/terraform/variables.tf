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

variable "deploy_ssh_public_keys" {
  description = "Environment-keyed SSH public keys for API deployment. Private keys are supplied independently as GitHub environment secrets."
  type        = map(string)
  sensitive   = true
  validation {
    condition     = alltrue([for k in keys(var.deploy_ssh_public_keys) : contains(["development", "production"], k)])
    error_message = "Keys may only be development and production."
  }
}

variable "ssh_cidr_blocks" {
  description = "Environment-keyed baseline IPv4 CIDRs allowed to SSH to each Lightsail instance."
  type        = map(list(string))
  validation {
    condition = toset(keys(var.ssh_cidr_blocks)) == toset(["development", "production"]) && alltrue([
      for cidrs in values(var.ssh_cidr_blocks) : length(cidrs) > 0 && alltrue([
        for cidr in cidrs : cidr != "0.0.0.0/0" && can(cidrnetmask(cidr))
      ])
    ])
    error_message = "Provide restricted IPv4 CIDRs for development and production; unrestricted SSH is rejected."
  }
}

variable "temporary_ssh_environment" {
  description = "Environment whose Lightsail SSH allowlist temporarily includes the current GitHub Actions runner. Null leaves both baseline allowlists unchanged."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.temporary_ssh_environment == null || contains(["development", "production"], var.temporary_ssh_environment)
    error_message = "temporary_ssh_environment must be development or production when set."
  }
}

variable "temporary_ssh_cidr" {
  description = "The current GitHub Actions runner public IPv4 address as a single /32. Used only for the selected deployment environment."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition = var.temporary_ssh_cidr == null || (
      can(cidrnetmask(var.temporary_ssh_cidr)) && can(regex("/32$", var.temporary_ssh_cidr))
    )
    error_message = "temporary_ssh_cidr must be a single IPv4 /32 when set."
  }
  validation {
    condition     = (var.temporary_ssh_environment == null) == (var.temporary_ssh_cidr == null)
    error_message = "temporary_ssh_environment and temporary_ssh_cidr must either both be set or both be null."
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
    condition     = var.dsql_auth_retention_days == null || (var.dsql_auth_retention_days > 0 && floor(var.dsql_auth_retention_days) == var.dsql_auth_retention_days)
    error_message = "When specified, dsql_auth_retention_days must be a positive whole number of days."
  }
}

variable "dsql_auth_alert_email" {
  description = "Optional owner-selected email recipient for DSQL authentication event alerts. SNS requires recipient confirmation."
  type        = string
  default     = null
}
