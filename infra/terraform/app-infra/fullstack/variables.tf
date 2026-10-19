variable "aws_region" {
  description = "Region for PawLocal application resources and Aurora DSQL."
  type        = string
  default     = "ap-southeast-2"
}

variable "root_domain" {
  description = "Existing public Route 53 hosted-zone name, without a trailing dot."
  type        = string
}

variable "cloudfront_certificate_arn" {
  description = "Existing ACM certificate ARN in us-east-1 covering the frontend CloudFront hostnames pawlocal-dev and pawlocal."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^arn:[^:]+:acm:us-east-1:[0-9]{12}:certificate/.+$", var.cloudfront_certificate_arn))
    error_message = "CloudFront certificates must be issued in us-east-1."
  }
}

variable "backend_image_digests" {
  description = "Environment-keyed immutable public GHCR image references for the Lightsail API deployment."
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
  description = "Absolute path to the Python interpreter with backend dependencies installed for Terraform's DSQL role bootstrap."
  type        = string
}

variable "enable_dsql_auth_event_capture" {
  description = "Capture DSQL DbConnect data events in a dedicated CloudTrail trail. Adds metered data-event and storage charges; this is security audit logging, not application telemetry."
  type        = bool
  default     = false
}

variable "dsql_auth_audit_bucket_name" {
  description = "Owner-selected S3 bucket name for DSQL authentication audit events; required when event capture is enabled."
  type        = string
  default     = null
  nullable    = true
}

variable "dsql_auth_retention_days" {
  description = "Owner-selected retention in days for DSQL authentication audit objects; required when event capture is enabled."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.dsql_auth_retention_days == null ? true : (var.dsql_auth_retention_days > 0 && floor(var.dsql_auth_retention_days) == var.dsql_auth_retention_days)
    error_message = "When specified, dsql_auth_retention_days must be a positive whole number of days."
  }
}

variable "dsql_auth_alert_email" {
  description = "Optional email for DSQL authentication-event notifications. SNS requires confirmation by the recipient."
  type        = string
  default     = null
}

variable "environment_sizes" {
  description = "Lightsail Container Service power and scale per environment."
  type = map(object({
    container_power = string
    scale           = number
    hostname        = string
    api_name        = string
    database_role   = string
  }))
  default = {
    development = { container_power = "micro", scale = 1, hostname = "pawlocal-dev", api_name = "api-dev", database_role = "pawlocal_development_app" }
    production  = { container_power = "medium", scale = 1, hostname = "pawlocal", api_name = "api", database_role = "pawlocal_production_app" }
  }

  validation {
    condition = alltrue([
      for config in values(var.environment_sizes) : contains(["nano", "micro", "small", "medium", "large", "xlarge"], config.container_power) && config.scale >= 1 && config.scale <= 20 && floor(config.scale) == config.scale
    ])
    error_message = "Use a supported Lightsail Container Service power and an integer scale from 1 to 20."
  }
}
