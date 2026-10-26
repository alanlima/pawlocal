variable "environment" {
  description = "Exact PawLocal environment owned by this module instance."
  type        = string
  validation {
    condition     = contains(["development", "production"], var.environment)
    error_message = "environment must be development or production."
  }
}

variable "aws_region" {
  description = "AWS region for regional PawLocal resources."
  type        = string
}

variable "project_name" {
  description = "Project tag value shared with the bootstrap IAM tag conditions. Existing DEC-009 resource names remain fixed; Issue #227 on-call resources, policies and SSM paths use this project prefix consistently."
  type        = string
  default     = "pawlocal"
  validation {
    condition     = var.project_name == trimspace(var.project_name) && length(var.project_name) >= 1 && length(var.project_name) <= 8 && can(regex("^[A-Za-z0-9._-]+$", var.project_name))
    error_message = "project_name must contain 1 through 8 ASCII letters, digits, periods, underscores, or hyphens so rendered IAM policies remain within their enforced size budgets."
  }
}

variable "cognito_password_policy" {
  description = "Environment-specific Cognito password-policy values; every other pool setting remains common."
  type = object({
    minimum_length    = number
    require_lowercase = bool
    require_uppercase = bool
    require_numbers   = bool
  })

  validation {
    condition = (
      var.cognito_password_policy.minimum_length >= 6 &&
      var.cognito_password_policy.minimum_length <= 99 &&
      floor(var.cognito_password_policy.minimum_length) == var.cognito_password_policy.minimum_length
    )
    error_message = "cognito_password_policy.minimum_length must be a whole number from 6 through 99."
  }
}

variable "cognito_pre_sign_up_role_arn" {
  description = "Optional separately approved override for the exact matching bootstrap-owned pre sign-up execution role."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.cognito_pre_sign_up_role_arn == null ||
      can(regex("^arn:[^:]+:iam::[0-9]{12}:role/pawlocal-(development|production)-cognito-pre-signup$", var.cognito_pre_sign_up_role_arn))
    )
    error_message = "cognito_pre_sign_up_role_arn must be null or a structurally valid PawLocal pre sign-up role ARN."
  }
}

variable "root_domain" {
  description = "Existing public Route 53 zone name without a trailing dot."
  type        = string
}

variable "route53_zone_id" {
  description = "Existing public Route 53 zone ID."
  type        = string
}

variable "detach_lightsail_certificate" {
  description = "Detach the retained Lightsail certificate from the service. False preserves the original custom-domain attachment; public API routing always uses CloudFront."
  type        = bool
  default     = false
  nullable    = false
}

variable "cloudfront_certificate_arn" {
  description = "Existing us-east-1 ACM certificate covering the environment frontend hostname."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^arn:[^:]+:acm:us-east-1:[0-9]{12}:certificate/.+$", var.cloudfront_certificate_arn))
    error_message = "cloudfront_certificate_arn must be a us-east-1 ACM certificate ARN."
  }
}

variable "terraform_apply_role_name" {
  description = "Matching bootstrap-owned Terraform apply role name."
  type        = string
  validation {
    condition     = var.terraform_apply_role_name == "pawlocal-${var.environment}-terraform-apply"
    error_message = "terraform_apply_role_name must match the selected environment."
  }
}

variable "frontend_publish_role_name" {
  description = "Matching bootstrap-owned frontend publisher role name."
  type        = string
  validation {
    condition     = var.frontend_publish_role_name == "pawlocal-${var.environment}-github-deploy"
    error_message = "frontend_publish_role_name must match the selected environment."
  }
}

variable "runtime_role_arn" {
  description = "Bootstrap-owned runtime role created after the Lightsail principal handoff. Empty keeps the API deployment and API DNS fail-closed."
  type        = string
  default     = ""
  validation {
    condition     = var.runtime_role_arn == "" || can(regex("^arn:[^:]+:iam::[0-9]{12}:role/pawlocal-${var.environment}-dsql-runtime$", var.runtime_role_arn))
    error_message = "runtime_role_arn must be empty or the matching bootstrap-owned runtime role ARN."
  }
}

variable "backend_image" {
  description = "Immutable public GHCR backend image. Empty creates no container deployment or API DNS record."
  type        = string
  default     = ""
  validation {
    condition     = var.backend_image == "" || can(regex("^ghcr\\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}$", var.backend_image))
    error_message = "backend_image must be empty or the PawLocal API image pinned to a sha256 digest."
  }
}

variable "teardown_enabled" {
  description = "Allow Terraform-managed application data deletion during an explicitly reviewed destroy. Normal plans must leave this false."
  type        = bool
  default     = false
}

variable "cloudfront_distribution_arn" {
  description = "Exact distribution ARN handed back after the first create-only apply. Empty denies distribution update/delete."
  type        = string
  default     = ""
}

variable "cloudfront_oac_arn" {
  description = "Exact origin access control ARN handed back after the first create-only apply. Empty denies OAC update/delete."
  type        = string
  default     = ""
}

variable "container_power" {
  description = "Approved Lightsail Container Service power."
  type        = string
  validation {
    condition     = contains(["nano", "micro", "small", "medium", "large", "xlarge"], var.container_power)
    error_message = "container_power must be a supported Lightsail Container Service size."
  }
}

variable "container_scale" {
  description = "Approved Lightsail Container Service scale."
  type        = number
  default     = 1
  validation {
    condition     = var.container_scale >= 1 && var.container_scale <= 20 && floor(var.container_scale) == var.container_scale
    error_message = "container_scale must be a whole number from 1 through 20."
  }
}
