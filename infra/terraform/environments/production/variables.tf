variable "aws_region" { type = string }
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
