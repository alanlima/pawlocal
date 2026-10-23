locals {
  configuration_suffixes = setunion(local.hosted_public_suffixes, toset([
    "frontend/base-url", "api/health-url", "frontend/bucket",
    "frontend/cloudfront-distribution-id", "frontend/cloudfront-distribution-arn", "frontend/cloudfront-oac-arn",
    "auth/client-id", "api/base-url", "auth/domain", "auth/redirect-uri", "auth/logout-uri", "auth/scopes"
  ]))
  configuration_parameter_arns = [
    for suffix in sort(tolist(local.configuration_suffixes)) :
    "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/pawlocal/${var.environment}/config/${suffix}"
  ]
  public_configuration = {
    frontend_base_url    = "https://${trimsuffix(aws_route53_record.frontend_a.fqdn, ".")}"
    api_base_url         = local.deployment_enabled ? "https://${trimsuffix(aws_route53_record.api[0].fqdn, ".")}/api/v1" : null
    api_health_url       = local.deployment_enabled ? "https://${trimsuffix(aws_route53_record.api[0].fqdn, ".")}/health" : null
    cognito_domain       = "https://${aws_cognito_user_pool_domain.application.domain}.auth.${var.aws_region}.amazoncognito.com"
    cognito_redirect_uri = one(aws_cognito_user_pool_client.browser.callback_urls)
    cognito_logout_uri   = one(aws_cognito_user_pool_client.browser.logout_urls)
    cognito_scopes       = join(" ", sort(tolist(aws_cognito_user_pool_client.browser.allowed_oauth_scopes)))
  }
  application_configuration_values = merge({
    "observability/enabled"                = tostring(local.hosted_telemetry_enabled)
    "frontend/telemetry-enabled"           = tostring(local.hosted_frontend_telemetry_enabled)
    "frontend/base-url"                    = local.public_configuration.frontend_base_url
    "frontend/bucket"                      = aws_s3_bucket.frontend.bucket
    "frontend/cloudfront-distribution-id"  = aws_cloudfront_distribution.frontend.id
    "frontend/cloudfront-distribution-arn" = aws_cloudfront_distribution.frontend.arn
    "frontend/cloudfront-oac-arn"          = aws_cloudfront_origin_access_control.frontend.arn
    "auth/client-id"                       = aws_cognito_user_pool_client.browser.id
    "auth/domain"                          = local.public_configuration.cognito_domain
    "auth/redirect-uri"                    = local.public_configuration.cognito_redirect_uri
    "auth/logout-uri"                      = local.public_configuration.cognito_logout_uri
    "auth/scopes"                          = local.public_configuration.cognito_scopes
    }, local.deployment_enabled ? {
    "api/base-url"   = local.public_configuration.api_base_url
    "api/health-url" = local.public_configuration.api_health_url
    } : {}, var.hosted_observability == null ? {} : {
    "grafana/stack-url"          = var.hosted_observability.stack_url
    "grafana/faro-collector-url" = var.hosted_observability.faro_collector_url
    }, var.hosted_observability == null ? {} : {
    for suffix, value in {
      "grafana/otlp-endpoint"    = var.hosted_observability.otlp_endpoint
      "grafana/otlp-instance-id" = var.hosted_observability.otlp_instance_id
    } : suffix => value if value != null
  })
}

data "aws_iam_policy_document" "configuration" {
  statement {
    sid    = "ManageOnlyOwnedConfigurationParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter", "ssm:ListTagsForResource", "ssm:PutParameter", "ssm:DeleteParameter",
      "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource"
    ]
    resources = local.configuration_parameter_arns
  }
}

resource "aws_iam_policy" "configuration" {
  name        = "pawlocal-${var.environment}-configuration"
  description = "Manage only Terraform-owned PawLocal ${var.environment} application configuration."
  policy      = data.aws_iam_policy_document.configuration.json
  tags        = local.common_tags
}

resource "aws_iam_role_policy_attachment" "configuration" {
  role       = var.terraform_apply_role_name
  policy_arn = aws_iam_policy.configuration.arn
}

resource "time_sleep" "configuration_permissions_propagation" {
  create_duration = "30s"
  triggers = {
    configuration_policy_sha256 = sha256(data.aws_iam_policy_document.configuration.json)
  }
  depends_on = [aws_iam_role_policy_attachment.configuration]
}

resource "aws_ssm_parameter" "configuration" {
  for_each = local.application_configuration_values

  name        = "/pawlocal/${var.environment}/config/${each.key}"
  description = "Terraform-generated PawLocal ${var.environment} ${each.key}."
  type        = "String"
  tier        = "Standard"
  value       = each.value
  # Default no-overwrite-on-create rejects colliding unmanaged parameters.
  tags = merge(local.common_tags, {
    "configuration-access" = "github-public"
  })
  depends_on = [time_sleep.configuration_permissions_propagation]
}
