output "environment_targets" {
  description = "Non-secret public endpoints, resources, and deployment IAM role ARNs, keyed by environment."
  value = { for name, config in local.environments : name => {
    frontend_url               = "https://${config.hostname}.${trimsuffix(var.root_domain, ".")}"
    api_health_url             = "https://${config.api_name}.${trimsuffix(var.root_domain, ".")}/health"
    api_hostname               = "${config.api_name}.${trimsuffix(var.root_domain, ".")}"
    api_container_service_name = aws_lightsail_container_service.api[name].name
    api_container_service_url  = aws_lightsail_container_service.api[name].url
    api_container_service_arn  = aws_lightsail_container_service.api[name].arn
    api_runtime_principal_arn  = aws_lightsail_container_service.api[name].principal_arn
    api_backend_image          = local.backend_images[name]
    frontend_bucket            = contains(keys(local.frontend_environments), name) ? aws_s3_bucket.frontend[name].bucket : null
    distribution_id            = contains(keys(local.frontend_environments), name) ? aws_cloudfront_distribution.app[name].id : null
    dsql_cluster_arn           = aws_dsql_cluster.app[name].arn
    dsql_endpoint              = "${aws_dsql_cluster.app[name].identifier}.dsql.${var.aws_region}.on.aws"
    dsql_database_role         = config.database_role
    cognito_user_pool_id       = aws_cognito_user_pool.app[name].id
    cognito_client_id          = aws_cognito_user_pool_client.app[name].id
    cognito_domain             = "https://${aws_cognito_user_pool_domain.app[name].domain}.auth.${var.aws_region}.amazoncognito.com"
    cognito_issuer             = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.app[name].id}"
    cognito_redirect_uri       = "https://${config.hostname}.${trimsuffix(var.root_domain, ".")}/auth/callback"
    cognito_logout_uri         = "https://${config.hostname}.${trimsuffix(var.root_domain, ".")}/"
    cognito_scopes             = "openid email profile"
  } }
}

output "shared_iam_targets" {
  description = "Exact application resource ARNs consumed by the shared IAM root when it builds least-privilege GitHub policies."
  value = { for name in keys(local.environments) : name => {
    frontend_bucket_arn       = contains(keys(local.frontend_environments), name) ? aws_s3_bucket.frontend[name].arn : null
    frontend_distribution_arn = contains(keys(local.frontend_environments), name) ? aws_cloudfront_distribution.app[name].arn : null
    frontend_distribution_id  = contains(keys(local.frontend_environments), name) ? aws_cloudfront_distribution.app[name].id : null
    frontend_function_arn     = contains(keys(local.frontend_environments), name) ? aws_cloudfront_function.spa[name].arn : null
    cognito_user_pool_arn     = aws_cognito_user_pool.app[name].arn
    api_container_service_arn = aws_lightsail_container_service.api[name].arn
    audit_bucket_arn          = try(aws_s3_bucket.cloudtrail[0].arn, null)
  } }
}

output "dsql_auth_alert_topic_arn" {
  description = "Present only when DSQL data-event capture and an alert email are configured. Confirm the SNS subscription before relying on delivery."
  value       = try(aws_sns_topic.dsql_auth[0].arn, null)
}
