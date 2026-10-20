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
    dsql_app_iam_principal_arn = local.dsql_app_principal_arns[name]
    aws_account_id             = data.aws_caller_identity.current.account_id
    api_backend_image          = local.backend_images[name]
    frontend_bucket            = contains(keys(local.frontend_environments), name) ? aws_s3_bucket.frontend[name].bucket : null
    distribution_id            = contains(keys(local.frontend_environments), name) ? aws_cloudfront_distribution.app[name].id : null
    oac_id                     = contains(keys(local.frontend_environments), name) ? aws_cloudfront_origin_access_control.frontend[name].id : null
    oac_arn                    = contains(keys(local.frontend_environments), name) ? "arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:origin-access-control/${aws_cloudfront_origin_access_control.frontend[name].id}" : null
    dsql_cluster_arn           = aws_dsql_cluster.app[name].arn
    dsql_endpoint              = "${aws_dsql_cluster.app[name].identifier}.dsql.${var.aws_region}.on.aws"
    dsql_database_role         = config.database_role
    deploy_role_arn            = contains(keys(local.frontend_environments), name) ? aws_iam_role.github_deploy[name].arn : null
    terraform_deploy_role_arn  = aws_iam_role.github_terraform_deploy[name].arn
    cognito_user_pool_id       = aws_cognito_user_pool.app[name].id
    cognito_client_id          = aws_cognito_user_pool_client.app[name].id
    cognito_domain             = "https://${aws_cognito_user_pool_domain.app[name].domain}.auth.${var.aws_region}.amazoncognito.com"
    cognito_issuer             = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.app[name].id}"
    cognito_redirect_uri       = "https://${config.hostname}.${trimsuffix(var.root_domain, ".")}/auth/callback"
    cognito_logout_uri         = "https://${config.hostname}.${trimsuffix(var.root_domain, ".")}/"
    cognito_scopes             = "openid email profile"
  } }
}

output "dsql_auth_alert_topic_arn" {
  description = "Present only when DSQL data-event capture and an alert email are configured. Confirm the SNS subscription before relying on delivery."
  value       = try(aws_sns_topic.dsql_auth[0].arn, null)
}
