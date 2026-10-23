variable "hosted_observability" {
  description = "Reviewed public Grafana bindings only. Null keeps hosted export disabled; runtime credentials are never Terraform inputs."
  type = object({
    enabled          = optional(bool, false)
    frontend_enabled = optional(bool)
    stack_url        = string
    stack_slug       = optional(string)
    faro_app_name    = optional(string)
    kms_key_arn      = optional(string)
    datasources = optional(object({
      metrics = optional(object({
        uid  = optional(string)
        name = optional(string)
      }))
      logs = optional(object({
        uid  = optional(string)
        name = optional(string)
      }))
      traces = optional(object({
        uid  = optional(string)
        name = optional(string)
      }))
      usage = optional(object({
        uid  = optional(string)
        name = optional(string)
      }))
    }))
    metrics_datasource_uid = optional(string)
    logs_datasource_uid    = optional(string)
    traces_datasource_uid  = optional(string)
    usage_datasource_uid   = optional(string)
  })
  default = null
}
