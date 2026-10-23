variable "hosted_observability" {
  description = "Reviewed public Grafana bindings only. Null keeps hosted export disabled; runtime credentials are never Terraform inputs."
  type = object({
    enabled            = optional(bool, false)
    frontend_enabled   = optional(bool)
    stack_url          = string
    otlp_endpoint      = optional(string)
    otlp_instance_id   = optional(string)
    faro_collector_url = string
    kms_key_arn        = optional(string)
  })
  default = null
}
