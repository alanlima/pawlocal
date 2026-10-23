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
  validation {
    condition = var.hosted_observability == null ? true : (
      can(regex("^https://[a-z0-9-]+[.]grafana[.]net/?$", var.hosted_observability.stack_url)) &&
      (var.hosted_observability.otlp_endpoint == null ? !var.hosted_observability.enabled : can(regex("^https://[a-z0-9.-]+[.]grafana[.]net/otlp/?$", var.hosted_observability.otlp_endpoint))) &&
      (var.hosted_observability.otlp_instance_id == null ? !var.hosted_observability.enabled : can(regex("^[0-9]{1,20}$", var.hosted_observability.otlp_instance_id))) &&
      can(regex("^https://[a-z0-9.-]+[.]grafana[.]net/collect/[A-Za-z0-9_-]+$", var.hosted_observability.faro_collector_url)) &&
      (var.hosted_observability.kms_key_arn == null || can(regex("^arn:${data.aws_partition.current.partition}:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:key/[0-9a-f-]{36}$", var.hosted_observability.kms_key_arn)))
    )
    error_message = "Hosted observability requires verified public Grafana HTTPS bindings and, when supplied, an existing matching KMS key."

  }
}

locals {
  hosted_telemetry_enabled          = var.hosted_observability == null ? false : var.hosted_observability.enabled
  hosted_frontend_telemetry_enabled = var.hosted_observability == null ? false : coalesce(var.hosted_observability.frontend_enabled, var.hosted_observability.enabled)
  hosted_public_suffixes            = toset(["observability/enabled", "frontend/telemetry-enabled", "grafana/stack-url", "grafana/otlp-endpoint", "grafana/otlp-instance-id", "grafana/faro-collector-url"])
  hosted_token_arn                  = "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/pawlocal/${var.environment}/secrets/grafana/otlp-token"
}
