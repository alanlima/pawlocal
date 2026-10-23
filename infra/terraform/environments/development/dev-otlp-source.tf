# DRAFT #241: independent source ownership survives disabling hosted exports.
# No workflow inputs, grants or live configuration are introduced here.
variable "dev_otlp_source_managed" {
  type    = bool
  default = false
}
variable "dev_otlp_source_write_revision" {
  type    = number
  default = 1
}
variable "dev_otlp_source_creation" {
  type = object({
    legacy_version       = number
    legacy_last_modified = string
  })
  default = null
}
variable "dev_otlp_source_creation_value" {
  type      = string
  sensitive = true
  ephemeral = true
  default   = null
}

data "aws_caller_identity" "dev_otlp_source" {}

module "dev_otlp_source" {
  source         = "../../modules/dev-otlp-source"
  account_id     = data.aws_caller_identity.dev_otlp_source.account_id
  aws_region     = var.aws_region
  managed        = var.dev_otlp_source_managed
  write_revision = var.dev_otlp_source_write_revision
  creation       = var.dev_otlp_source_creation
  creation_value = var.dev_otlp_source_creation_value
}
