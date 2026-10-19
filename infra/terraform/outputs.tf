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
  description = "Existing-root-state production frontend publisher role ARN for the GitHub Actions production environment."
  value       = aws_iam_role.github_deploy.arn
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
      deploy_role_arn = aws_iam_role.github_deploy.arn
    })
  }
}

output "dsql_access_keys" {
  description = "Environment-scoped DSQL IAM access-key IDs and PGP-encrypted secrets from the Terraform-managed IAM access keys."
  sensitive   = true
  value       = module.fullstack.dsql_access_keys
}
