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
    })
  }
}

output "shared_iam_targets" {
  description = "Exact application resource ARNs consumed by the shared IAM root when it builds least-privilege GitHub policies."
  value = {
    development = module.fullstack.shared_iam_targets.development
    production = merge(module.fullstack.shared_iam_targets.production, {
      frontend_bucket_arn       = aws_s3_bucket.site.arn
      frontend_distribution_arn = aws_cloudfront_distribution.site.arn
      frontend_distribution_id  = aws_cloudfront_distribution.site.id
      frontend_function_arn     = aws_cloudfront_function.site_spa.arn
    })
  }
}
