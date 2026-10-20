variable "aws_region" {
  description = "AWS region used by the Terraform backend and regional application permissions."
  type        = string
  default     = "ap-southeast-2"
}

variable "terraform_state_bucket_name" {
  description = "Existing versioned, encrypted S3 bucket used by all PawLocal Terraform states."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository in owner/name format."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/name format."
  }
}

variable "github_owner_id" {
  description = "Immutable numeric GitHub owner ID used in the repository's configured OIDC subject."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must be a numeric immutable GitHub owner ID."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID used in the repository's configured OIDC subject."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a numeric immutable GitHub repository ID."
  }
}

variable "manage_github_oidc_provider" {
  description = "Initially false while the existing root owns the provider; set true after the approved recovery destroy so this state creates it."
  type        = bool
  default     = false
}

variable "route53_zone_id" {
  description = "Existing PawLocal public hosted zone identifier used to scope DNS record actions."
  type        = string
}

variable "domain_name" {
  description = "Existing root domain for precise Route 53 record name conditions."
  type        = string
}

variable "development_oac_arn" {
  description = "Exact development CloudFront OAC ARN, supplied after the first environment apply to scope OAC read/update/delete permissions. Empty only during initial OAC creation."
  type        = string
  default     = ""
  validation {
    condition     = var.development_oac_arn == "" || can(regex("^arn:[^:]+:cloudfront::[0-9]{12}:origin-access-control/[A-Za-z0-9]+$", var.development_oac_arn))
    error_message = "development_oac_arn must be empty or an exact CloudFront OAC ARN."
  }
}

variable "production_oac_arn" {
  description = "Exact production CloudFront OAC ARN, supplied after the first environment apply to scope OAC read/update/delete permissions. Empty only during initial OAC creation."
  type        = string
  default     = ""
  validation {
    condition     = var.production_oac_arn == "" || can(regex("^arn:[^:]+:cloudfront::[0-9]{12}:origin-access-control/[A-Za-z0-9]+$", var.production_oac_arn))
    error_message = "production_oac_arn must be empty or an exact CloudFront OAC ARN."
  }
}

variable "oac_create_environment" {
  description = "Select at most one environment for initial or replacement OAC creation. That environment's apply role temporarily receives CreateOriginAccessControl on Resource=* and OAC read access; use empty after its exact ARN handoff."
  type        = string
  default     = ""
  validation {
    condition     = contains(["", "development", "production"], var.oac_create_environment)
    error_message = "oac_create_environment must be empty, development, or production."
  }
}
