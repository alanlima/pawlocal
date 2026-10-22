variable "aws_region" { type = string }
variable "project_name" {
  description = "Project tag value shared with the bootstrap IAM tag conditions. Deterministic pawlocal-* resource names remain fixed by DEC-009."
  type        = string
  default     = "pawlocal"
  validation {
    condition     = var.project_name == trimspace(var.project_name) && length(var.project_name) >= 1 && length(var.project_name) <= 8 && can(regex("^[A-Za-z0-9._-]+$", var.project_name))
    error_message = "project_name must contain 1 through 8 ASCII letters, digits, periods, underscores, or hyphens so rendered IAM policies remain within their enforced size budgets."
  }
}
variable "root_domain" { type = string }
variable "route53_zone_id" { type = string }
variable "cloudfront_certificate_arn" {
  type      = string
  sensitive = true
}
variable "runtime_role_arn" {
  type    = string
  default = ""
}
variable "backend_image" {
  type    = string
  default = ""
}
variable "cloudfront_distribution_arn" {
  type    = string
  default = ""
}
variable "cloudfront_oac_arn" {
  type    = string
  default = ""
}
variable "teardown_enabled" {
  description = "Protected destroy preparation switch. Ordinary production operations must leave this false."
  type        = bool
  default     = false
}
