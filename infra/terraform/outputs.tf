output "site_url" {
  description = "HTTPS URL of the PawLocal frontend."
  value       = "https://${local.site_fqdn}"
}

output "site_bucket_name" {
  description = "Private S3 bucket name for published frontend assets."
  value       = aws_s3_bucket.site.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID used by GitHub Actions invalidations."
  value       = aws_cloudfront_distribution.site.id
}

output "github_deploy_role_arn" {
  description = "Existing production frontend publisher role ARN retained outside the application Terraform state for later bootstrap import."
  value       = data.aws_iam_role.github_deploy.arn
}

output "environment_targets" {
  description = "Deployment targets for development and production, with production frontend assets mapped to the existing root-state bucket/distribution."
  value = {
    development = merge(module.fullstack.environment_targets["development"], {
      frontend_bucket = module.fullstack.environment_targets["development"].frontend_bucket
      distribution_id = module.fullstack.environment_targets["development"].distribution_id
    })
    production = merge(module.fullstack.environment_targets["production"], {
      frontend_url    = "https://${local.site_fqdn}"
      frontend_bucket = aws_s3_bucket.site.bucket
      distribution_id = aws_cloudfront_distribution.site.id
      deploy_role_arn = data.aws_iam_role.github_deploy.arn
    })
  }
}
