variable "hosted_observability" {
  description = "Reviewed public Grafana bindings only. Null keeps hosted export disabled; runtime credentials are never Terraform inputs."
  type = object({
    enabled          = optional(bool, false)
    frontend_enabled = optional(bool)
    stack_url        = string
    stack_slug       = optional(string)
    faro_app_name    = optional(string)
    kms_key_arn      = optional(string)
  })
  default = null
}
