module "pawlocal" {
  source = "../../modules/pawlocal-environment"

  environment                  = "development"
  aws_region                   = var.aws_region
  root_domain                  = var.root_domain
  route53_zone_id              = var.route53_zone_id
  cloudfront_certificate_arn   = var.cloudfront_certificate_arn
  cognito_pre_sign_up_role_arn = var.cognito_pre_sign_up_role_arn
  cognito_password_policy = {
    minimum_length    = 8
    require_lowercase = false
    require_uppercase = false
    require_numbers   = false
  }
  terraform_apply_role_name   = "pawlocal-development-terraform-apply"
  frontend_publish_role_name  = "pawlocal-development-github-deploy"
  runtime_role_arn            = var.runtime_role_arn
  backend_image               = var.backend_image
  cloudfront_distribution_arn = var.cloudfront_distribution_arn
  cloudfront_oac_arn          = var.cloudfront_oac_arn
  container_power             = "micro"
  container_scale             = 1
}
