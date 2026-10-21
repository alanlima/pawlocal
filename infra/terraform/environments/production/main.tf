module "pawlocal" {
  source = "../../modules/pawlocal-environment"

  environment                 = "production"
  aws_region                  = var.aws_region
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
}
