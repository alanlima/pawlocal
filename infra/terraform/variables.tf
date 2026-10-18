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

variable "manage_github_oidc_provider" {
  description = "Create the account-wide GitHub Actions OIDC provider only when the AWS account does not already have one. Leave false to use the existing shared provider."
  type        = bool
  default     = false
}
