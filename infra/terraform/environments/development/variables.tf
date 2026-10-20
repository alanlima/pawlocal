variable "aws_region" {
  description = "AWS region for the PawLocal development environment."
  type        = string
  default     = "ap-southeast-2"
}

variable "root_domain" {
  description = "Existing public Route 53 zone name, without a trailing dot."
  type        = string
}

variable "cloudfront_certificate_arn" {
  description = "Existing ACM certificate ARN in us-east-1 covering pawlocal-dev and api-dev hostnames."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^arn:[^:]+:acm:us-east-1:[0-9]{12}:certificate/.+$", var.cloudfront_certificate_arn))
    error_message = "CloudFront certificates must be issued in us-east-1."
  }
}

variable "github_repository" { type = string }
variable "github_owner_id" { type = string }
variable "github_repository_id" { type = string }

variable "terraform_state_bucket_name" {
  description = "Existing S3 bucket used for independent PawLocal Terraform environment states."
  type        = string
}

variable "backend_image_digest" {
  description = "Immutable public GHCR image reference used by the development API."
  type        = string
  validation {
    condition     = can(regex("^ghcr\\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}$", var.backend_image_digest))
    error_message = "The backend image must be pinned to a public GHCR sha256 digest."
  }
}
