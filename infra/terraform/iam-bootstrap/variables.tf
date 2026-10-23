variable "aws_region" {
  description = "AWS region used by the Terraform backend and regional application permissions."
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Project tag value for bootstrap-owned resources and their tag-based permission conditions. Existing DEC-009 resource names remain fixed; Issue #227 on-call resources, policies and SSM paths use this project prefix consistently."
  type        = string
  default     = "pawlocal"

  validation {
    condition     = var.project_name == trimspace(var.project_name) && length(var.project_name) >= 1 && length(var.project_name) <= 8 && can(regex("^[A-Za-z0-9._-]+$", var.project_name))
    error_message = "project_name must contain 1 through 8 ASCII letters, digits, periods, underscores, or hyphens so rendered IAM policies remain within their enforced size budgets."
  }
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
  description = "Whether this bootstrap state manages the shared GitHub OIDC provider. Set true with import_existing_github_oidc_provider only after the application root has detached it using a reviewed removed block with destroy=false."
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

variable "development_lightsail_principal_arn" {
  description = "Exact principal_arn output from the development Lightsail container service. Leave empty until the foundation exists; bootstrap then creates the runtime role with exact Lightsail and development-seed trust."
  type        = string
  default     = ""
  validation {
    condition     = var.development_lightsail_principal_arn == "" || can(regex("^arn:[^:]+:iam::[0-9]{12}:role/.+$", var.development_lightsail_principal_arn))
    error_message = "development_lightsail_principal_arn must be empty or an IAM role ARN returned as the exact Lightsail principal_arn."
  }
}

variable "production_lightsail_principal_arn" {
  description = "Exact principal_arn output from the production Lightsail container service. Leave empty until the production foundation exists."
  type        = string
  default     = ""
  validation {
    condition     = var.production_lightsail_principal_arn == "" || can(regex("^arn:[^:]+:iam::[0-9]{12}:role/.+$", var.production_lightsail_principal_arn))
    error_message = "production_lightsail_principal_arn must be empty or an IAM role ARN returned as the exact Lightsail principal_arn."
  }
}

variable "import_existing_dsql_service_linked_role" {
  description = "Set true for the reviewed bootstrap plan when AWS already has AWSServiceRoleForAuroraDsql; Terraform will import its fixed ARN instead of creating a duplicate. Leave false when the role does not exist."
  type        = bool
  default     = false
}

variable "import_existing_development_deploy_role" {
  description = "Set true only for the reviewed bootstrap plan that declaratively imports the verified existing pawlocal-development-github-deploy role. Production is created normally; no application resource is imported."
  type        = bool
  default     = false
}

variable "import_existing_github_oidc_provider" {
  description = "Set true only after the application root has used its reviewed removed block with destroy=false; Terraform then imports the existing fixed GitHub OIDC provider into this bootstrap state."
  type        = bool
  default     = false
  validation {
    condition     = !var.import_existing_github_oidc_provider || var.manage_github_oidc_provider
    error_message = "import_existing_github_oidc_provider requires manage_github_oidc_provider=true."
  }
}
