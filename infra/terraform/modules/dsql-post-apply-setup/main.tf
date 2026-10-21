terraform {
  required_version = "= 1.14.3"
}

variable "cluster_identity" {
  description = "Exact DSQL cluster identity used only to derive the lifecycle digest."
  type        = string
}

variable "runtime_identity" {
  description = "Exact runtime IAM identity used only to derive the lifecycle digest."
  type        = string
}

variable "setup_revision" {
  description = "Explicit reviewed setup revision controlling postcondition reassertion."
  type        = string
}

variable "command" {
  description = "Caller-owned setup command. Production callers must pass the protected PawLocal entrypoint."
  type        = string
  validation {
    condition     = trimspace(var.command) != ""
    error_message = "command must not be empty."
  }
}

variable "working_directory" {
  description = "Existing working directory for the setup command."
  type        = string
}

variable "environment" {
  description = "Non-secret process environment for the setup command."
  type        = map(string)
  default     = {}
}

resource "terraform_data" "setup" {
  triggers_replace = {
    cluster_identity_sha256 = sha256(var.cluster_identity)
    runtime_identity_sha256 = sha256(var.runtime_identity)
    setup_revision_sha256   = sha256(var.setup_revision)
  }

  provisioner "local-exec" {
    command     = var.command
    quiet       = true
    working_dir = var.working_directory
    environment = var.environment
  }
}

output "completion_id" {
  description = "Terraform lifecycle identity recorded only after the setup command succeeds."
  value       = terraform_data.setup.id
}

output "trigger_digests" {
  description = "Non-secret digests controlling setup replacement."
  value       = terraform_data.setup.triggers_replace
}
