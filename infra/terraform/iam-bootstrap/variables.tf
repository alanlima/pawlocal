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

variable "development_frontend_bucket_arn" {
  description = "Exact development frontend bucket ARN from the reviewed development foundation output; empty before that output exists."
  type        = string
  default     = ""
  validation {
    condition     = var.development_frontend_bucket_arn == "" || can(regex("^arn:[^:]+:s3:::pawlocal-development-[a-z0-9-]+$", var.development_frontend_bucket_arn))
    error_message = "development_frontend_bucket_arn must be empty or the exact PawLocal development frontend bucket ARN."
  }
}

variable "production_frontend_bucket_arn" {
  description = "Exact production frontend bucket ARN from the reviewed production foundation output; empty before that output exists."
  type        = string
  default     = ""
  validation {
    condition     = var.production_frontend_bucket_arn == "" || can(regex("^arn:[^:]+:s3:::pawlocal-production-[a-z0-9-]+$", var.production_frontend_bucket_arn))
    error_message = "production_frontend_bucket_arn must be empty or the exact PawLocal production frontend bucket ARN."
  }
}

variable "development_distribution_arn" {
  description = "Exact development CloudFront distribution ARN from the reviewed development Actions output. Empty disables cloudfront:UpdateDistribution for development until the bootstrap state is updated with the ARN."
  type        = string
  default     = ""
  validation {
    condition     = var.development_distribution_arn == "" || can(regex("^arn:[^:]+:cloudfront::[0-9]{12}:distribution/[A-Z0-9]+$", var.development_distribution_arn))
    error_message = "development_distribution_arn must be empty or an exact CloudFront distribution ARN."
  }
}

variable "production_distribution_arn" {
  description = "Exact production CloudFront distribution ARN from the reviewed production Actions output. Empty disables cloudfront:UpdateDistribution for production until the bootstrap state is updated with the ARN."
  type        = string
  default     = ""
  validation {
    condition     = var.production_distribution_arn == "" || can(regex("^arn:[^:]+:cloudfront::[0-9]{12}:distribution/[A-Z0-9]+$", var.production_distribution_arn))
    error_message = "production_distribution_arn must be empty or an exact CloudFront distribution ARN."
  }
}

variable "development_dsql_cluster_arn" {
  description = "Exact development Aurora DSQL cluster ARN from the reviewed development foundation output; empty before that output exists."
  type        = string
  default     = ""
  validation {
    condition     = var.development_dsql_cluster_arn == "" || can(regex("^arn:[^:]+:dsql:[^:]+:[0-9]{12}:cluster/[A-Za-z0-9-]+$", var.development_dsql_cluster_arn))
    error_message = "development_dsql_cluster_arn must be empty or an exact Aurora DSQL cluster ARN."
  }
}

variable "development_lightsail_principal_arn" {
  description = "Exact principal_arn output from the development Lightsail container service. Leave empty until the foundation exists; bootstrap then creates the runtime role with exact Lightsail and development-seed trust."
  type        = string
  default     = ""
  validation {
    condition     = var.development_lightsail_principal_arn == "" || can(regex("^arn:[^:]+:iam::[0-9]{12}:role/.+$", var.development_lightsail_principal_arn))
    error_message = "development_lightsail_principal_arn must be empty or an IAM role ARN returned as the exact Lightsail principal_arn."
  }
}

variable "import_existing_dsql_service_linked_role" {
  description = "Set true for the reviewed bootstrap plan when AWS already has AWSServiceRoleForAuroraDsql; Terraform will import its fixed ARN instead of creating a duplicate. Leave false when the role does not exist."
  type        = bool
  default     = false
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
