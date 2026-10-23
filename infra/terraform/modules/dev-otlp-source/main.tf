terraform {
  required_version = "= 1.14.3"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.1"
    }
  }
}

variable "account_id" { type = string }
variable "aws_region" { type = string }
variable "managed" {
  description = "Stable DEV source ownership, independent of telemetry export enablement. No live setup approval is implied."
  type        = bool
  default     = false
}
variable "write_revision" {
  type    = number
  default = 1
  validation {
    condition     = var.write_revision >= 1 && var.write_revision == floor(var.write_revision)
    error_message = "A positive integer write revision is required."
  }
}
variable "creation" {
  description = "Explicit first-creation selection; protected input helper verifies this public legacy metadata atomically with its value."
  type = object({
    legacy_version       = number
    legacy_last_modified = string
  })
  default = null
  validation {
    condition = var.creation == null ? true : (
      var.managed && var.write_revision == 1 && var.creation.legacy_version == 1 && can(formatdate("YYYY", var.creation.legacy_last_modified))
    )
    error_message = "First creation must explicitly select managed DEV revision one and reviewed legacy version-one server metadata."
  }
}
variable "creation_value" {
  type      = string
  sensitive = true
  ephemeral = true
  default   = null
  validation {
    condition     = var.creation == null ? var.creation_value == null : (var.creation_value == null ? false : length(trimspace(var.creation_value)) > 0)
    error_message = "Creation requires a nonempty protected ephemeral input; maintenance must not receive one."
  }
}

locals {
  name = "/pawlocal/development/secrets/grafana/otlp-token-v1"
  arn  = "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter${local.name}"
}

ephemeral "aws_ssm_parameter" "current" {
  count           = var.managed && var.creation == null ? 1 : 0
  arn             = local.arn
  with_decryption = true
}

resource "aws_ssm_parameter" "token" {
  count            = var.managed ? 1 : 0
  name             = local.name
  description      = "Terraform-owned PawLocal development OTLP ingestion credential."
  type             = "SecureString"
  tier             = "Standard"
  value_wo         = var.creation != null ? var.creation_value : ephemeral.aws_ssm_parameter.current[0].value
  value_wo_version = var.write_revision
  tags = {
    project     = "pawlocal"
    environment = "development"
    managedby   = "terraform"
  }
  # Unset overwrite rejects an existing unmanaged target on initial creation.
  lifecycle {
    prevent_destroy = true
    precondition {
      condition = var.creation != null ? true : (
        ephemeral.aws_ssm_parameter.current[0].type == "SecureString" && length(trimspace(ephemeral.aws_ssm_parameter.current[0].value)) > 0
      )
      error_message = "Managed DEV source must remain a nonempty SecureString; there is no legacy fallback."
    }
  }
}
