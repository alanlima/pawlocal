module "pawlocal" {
  source = "../../modules/pawlocal-environment"

  providers = {
    aws                    = aws
    aws.cognito_deployment = aws.cognito_deployment
  }

  environment                 = "production"
  aws_region                  = var.aws_region
  project_name                = var.project_name
  root_domain                 = var.root_domain
  route53_zone_id             = var.route53_zone_id
  cloudfront_certificate_arn  = var.cloudfront_certificate_arn
  terraform_apply_role_name   = "pawlocal-production-terraform-apply"
  frontend_publish_role_name  = "pawlocal-production-github-deploy"
  runtime_role_arn            = var.runtime_role_arn
  backend_image               = var.backend_image
  cloudfront_distribution_arn = var.cloudfront_distribution_arn
  cloudfront_oac_arn          = var.cloudfront_oac_arn
  teardown_enabled            = var.teardown_enabled
  container_power             = "medium"
  container_scale             = 1

  cognito_pre_sign_up_role_arn = var.cognito_pre_sign_up_role_arn
  cognito_password_policy = {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
  }
}
