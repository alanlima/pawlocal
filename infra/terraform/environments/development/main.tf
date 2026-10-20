locals {
  environment = "development"
  environment_size = {
    container_power = "micro"
    scale           = 1
    hostname        = "pawlocal-dev"
    api_name        = "api-dev"
    database_role   = "pawlocal_development_app"
  }
  common_tags = {
    costcenter  = "personal"
    environment = local.environment
    managedby   = "terraform"
    project     = "pawlocal"
    component   = "fullstack-mvp"
    workload    = "application"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.common_tags }
}

module "fullstack" {
  source = "../../fullstack"

  aws_region                     = var.aws_region
  root_domain                    = var.root_domain
  cloudfront_certificate_arn     = var.cloudfront_certificate_arn
  backend_image_digests          = trimspace(coalesce(var.backend_image_digest, "")) == "" ? {} : { (local.environment) = var.backend_image_digest }
  environment_sizes              = { (local.environment) = local.environment_size }
  enable_dsql_auth_event_capture = false
  dsql_runtime_role_arn          = var.dsql_runtime_role_arn
}
