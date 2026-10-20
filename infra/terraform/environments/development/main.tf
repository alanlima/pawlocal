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

  aws_region                      = var.aws_region
  root_domain                     = var.root_domain
  cloudfront_certificate_arn      = var.cloudfront_certificate_arn
  github_repository               = var.github_repository
  github_owner_id                 = var.github_owner_id
  github_repository_id            = var.github_repository_id
  terraform_state_bucket_name     = var.terraform_state_bucket_name
  additional_frontend_bucket_arns = []
  manage_github_oidc_provider     = false
  backend_image_digests           = { (local.environment) = var.backend_image_digest }
  environment_sizes               = { (local.environment) = local.environment_size }
  enable_dsql_auth_event_capture  = false
}
