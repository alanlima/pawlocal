variable "oncall_receiver" {
  description = "Public operator-only receiver configuration. Null is default-disabled; secret values are runtime SSM SecureStrings, never Terraform inputs."
  type = object({
    app_id           = string
    installation_id  = string
    repository_id    = string
    repository       = string
    enforce_guards   = optional(bool, false)
    allowed_services = set(string)
    allowed_alerts   = optional(set(string), [])
    kms_key_arn      = optional(string)
  })
  default = null
}

provider "aws" {
  alias   = "oncall_deployment"
  region  = var.aws_region
  profile = var.oncall_receiver == null ? null : "${var.project_name}-oncall-deployment"
  default_tags {
    tags = {
      project     = var.project_name
      environment = "development"
      managedby   = "terraform"
    }
  }
}
output "oncall_receiver_url" {
  description = "Public receiver endpoint, null until explicitly enabled and applied."
  value       = module.pawlocal.oncall_receiver_url
}
