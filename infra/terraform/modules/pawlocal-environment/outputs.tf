output "targets" {
  description = "Non-secret environment targets and bootstrap handoff identifiers."
  value = {
    environment                 = var.environment
    aws_account_id              = data.aws_caller_identity.current.account_id
    aws_region                  = var.aws_region
    frontend_url                = "https://${local.frontend_hostname}"
    api_base_url                = "https://${local.api_hostname}/api/v1"
    api_health_url              = "https://${local.api_hostname}/health"
    frontend_bucket             = aws_s3_bucket.frontend.bucket
    cloudfront_distribution_id  = aws_cloudfront_distribution.frontend.id
    cloudfront_distribution_arn = aws_cloudfront_distribution.frontend.arn
    cloudfront_oac_arn          = aws_cloudfront_origin_access_control.frontend.arn
    lightsail_service_name      = aws_lightsail_container_service.api.name
    lightsail_principal_arn     = aws_lightsail_container_service.api.principal_arn
    dsql_cluster_arn            = aws_dsql_cluster.application.arn
    dsql_endpoint               = "${aws_dsql_cluster.application.identifier}.dsql.${var.aws_region}.on.aws"
    dsql_database_role          = local.database_role
    runtime_role_arn            = var.runtime_role_arn == "" ? null : var.runtime_role_arn
    cognito_user_pool_id        = aws_cognito_user_pool.application.id
    cognito_client_id           = aws_cognito_user_pool_client.browser.id
    cognito_domain              = "https://${aws_cognito_user_pool_domain.application.domain}.auth.${var.aws_region}.amazoncognito.com"
    cognito_redirect_uri        = one(aws_cognito_user_pool_client.browser.callback_urls)
    cognito_logout_uri          = one(aws_cognito_user_pool_client.browser.logout_urls)
    cognito_scopes              = "openid email profile"
    backend_image               = var.backend_image == "" ? null : var.backend_image
  }
}
