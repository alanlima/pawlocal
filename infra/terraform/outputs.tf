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
  description = "IAM role ARN to configure as the GitHub Actions AWS_ROLE_ARN repository variable."
  value       = aws_iam_role.github_deploy.arn
}
