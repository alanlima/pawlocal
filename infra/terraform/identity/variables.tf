variable "aws_region" {
  type    = string
  default = "ap-southeast-2"
}

variable "terraform_state_bucket_name" {
  description = "Bucket containing the separately managed IAM bootstrap Terraform state."
  type        = string
}

variable "target_environment" {
  description = "Environment whose pre-created app roles receive their fixed managed policies."
  type        = string
  validation {
    condition     = contains(["development", "production"], var.target_environment)
    error_message = "The identity stage supports development or production only."
  }
}
