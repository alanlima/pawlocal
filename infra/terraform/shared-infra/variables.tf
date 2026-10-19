variable "aws_region" {
  description = "AWS region containing PawLocal deployment roles and the application state."
  type        = string
  default     = "ap-southeast-2"
}

variable "terraform_state_bucket_name" {
  description = "Existing versioned, encrypted S3 bucket used for both PawLocal Terraform state keys."
  type        = string
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
  description = "Immutable numeric GitHub owner ID used in OIDC subject claims."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must be a numeric immutable owner ID."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID used in OIDC subject claims."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a numeric immutable repository ID."
  }
}
