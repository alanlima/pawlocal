data "aws_route53_zone" "root" {
  name         = "${trimsuffix(var.root_domain, ".")}."
  private_zone = false
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
locals {
  environments          = var.environment_sizes
  frontend_environments = local.environments

  common_tags = {
    costcenter = "personal"
    managedby  = "terraform"
    project    = "pawlocal"
    component  = "fullstack-mvp"
    workload   = "application"
  }

  api_hostnames = {
    for environment, config in local.environments : environment => "${config.api_name}.${trimsuffix(var.root_domain, ".")}"
  }

  # Container service deployment config is Terraform state. The image is an
  # immutable public GHCR digest, and the environment map contains no secrets.
  backend_images = {
    for environment in keys(local.environments) : environment => lookup(var.backend_image_digests, environment, null)
  }

  dsql_app_principal_arns = {
    for environment in keys(local.environments) : environment => (
      environment == "development"
      ? (trimspace(coalesce(var.dsql_runtime_role_arn, "")) == "" ? null : var.dsql_runtime_role_arn)
      : aws_lightsail_container_service.api[environment].principal_arn
    )
  }
}

resource "random_id" "bucket_suffix" {
  for_each    = local.frontend_environments
  byte_length = 3
}

resource "aws_s3_bucket" "frontend" {
  for_each      = local.frontend_environments
  bucket        = "pawlocal-${each.key}-${random_id.bucket_suffix[each.key].hex}"
  force_destroy = false
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  for_each = local.frontend_environments
  bucket   = aws_s3_bucket.frontend[each.key].id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  for_each                = local.frontend_environments
  bucket                  = aws_s3_bucket.frontend[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  for_each = local.frontend_environments
  bucket   = aws_s3_bucket.frontend[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  for_each                          = local.frontend_environments
  name                              = "pawlocal-${each.key}-frontend-oac"
  description                       = "Private S3 origin for PawLocal ${each.key}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_dsql_cluster" "app" {
  for_each                    = local.environments
  deletion_protection_enabled = true
  kms_encryption_key          = "AWS_OWNED_KMS_KEY"
  tags = {
    Name        = "pawlocal-${each.key}"
    environment = each.key
    purpose     = "pawlocal-app-database"
  }
}

resource "aws_lightsail_certificate" "api" {
  for_each = local.environments
  # AWS rejected the original service-derived names as already existing, even
  # though they were absent from the certificate listing. Use migration names.
  name        = "pawlocal-${each.key}-api-migration-20261019"
  domain_name = local.api_hostnames[each.key]
  tags        = merge(local.common_tags, { environment = each.key })
}

resource "aws_route53_record" "api_certificate_validation" {
  for_each = local.environments
  zone_id  = data.aws_route53_zone.root.zone_id
  name     = one(aws_lightsail_certificate.api[each.key].domain_validation_options).resource_record_name
  type     = one(aws_lightsail_certificate.api[each.key].domain_validation_options).resource_record_type
  records  = [one(aws_lightsail_certificate.api[each.key].domain_validation_options).resource_record_value]
  ttl      = 60
}

resource "aws_lightsail_container_service" "api" {
  for_each    = local.environments
  name        = "pawlocal-${each.key}-api"
  power       = each.value.container_power
  scale       = each.value.scale
  is_disabled = false

  public_domain_names {
    certificate {
      certificate_name = aws_lightsail_certificate.api[each.key].name
      domain_names     = [local.api_hostnames[each.key]]
    }
  }

  depends_on = [aws_route53_record.api_certificate_validation]
}

# Lightsail's runtime principal belongs to AWS's Lightsail account. Aurora
# DSQL does not support cross-account cluster-policy grants, so the service
# assumes a narrowly scoped PawLocal-account role for development DB access.
resource "aws_lightsail_container_service_deployment_version" "api" {
  for_each = {
    for environment, config in local.environments : environment => config
    if local.backend_images[environment] != null
  }

  depends_on   = [aws_dsql_cluster_policy.api_connect]
  service_name = aws_lightsail_container_service.api[each.key].name

  container {
    container_name = "pawlocal-api"
    image          = local.backend_images[each.key]
    environment = merge({
      AWS_REGION                     = var.aws_region
      PAWLOCAL_RELEASE_ENVIRONMENT   = each.key
      PAWLOCAL_RELEASE_IMAGE_DIGEST  = split("@", local.backend_images[each.key])[1]
      PAWLOCAL_DATABASE_PROVIDER     = "aurora_dsql"
      PAWLOCAL_DATABASE_URL          = "auroradsql+psycopg://${each.value.database_role}@${aws_dsql_cluster.app[each.key].identifier}.dsql.${var.aws_region}.on.aws/postgres?application_name=pawlocal-${each.key}"
      PAWLOCAL_COGNITO_ISSUER        = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.app[each.key].id}"
      PAWLOCAL_COGNITO_APP_CLIENT_ID = aws_cognito_user_pool_client.app[each.key].id
      PAWLOCAL_CORS_ORIGINS          = "[\"https://${each.value.hostname}.${trimsuffix(var.root_domain, ".")}\"]"
      PAWLOCAL_TELEMETRY_ENABLED     = "false"
      OTEL_SDK_DISABLED              = "true"
      }, each.key == "development" && trimspace(coalesce(var.dsql_runtime_role_arn, "")) != "" ? {
      PAWLOCAL_DSQL_ASSUME_ROLE_ARN = var.dsql_runtime_role_arn
    } : {})
    ports = {
      "8000" = "HTTP"
    }
  }

  public_endpoint {
    container_name = "pawlocal-api"
    container_port = 8000

    health_check {
      path                = "/health"
      interval_seconds    = 30
      timeout_seconds     = 5
      healthy_threshold   = 2
      unhealthy_threshold = 3
      success_codes       = "200"
    }
  }

  lifecycle {
    precondition {
      condition     = each.key != "development" || trimspace(coalesce(var.dsql_runtime_role_arn, "")) != ""
      error_message = "Apply the separate identity state and provide dsql_runtime_role_arn before deploying the development API."
    }
  }
}

resource "aws_dsql_cluster_policy" "api_connect" {
  for_each   = local.environments
  identifier = aws_dsql_cluster.app[each.key].identifier
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Sid       = "DelegateToAccountIdentities"
          Effect    = "Allow"
          Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
          Action    = "dsql:DbConnectAdmin"
          Resource  = aws_dsql_cluster.app[each.key].arn
        }
      ],
      each.key == "development" && trimspace(coalesce(var.dsql_runtime_role_arn, "")) != "" ? [
        {
          Sid       = "AllowDevelopmentRuntimeRole"
          Effect    = "Allow"
          Principal = { AWS = var.dsql_runtime_role_arn }
          Action    = "dsql:DbConnect"
          Resource  = aws_dsql_cluster.app[each.key].arn
          Condition = { StringEquals = { "dsql:DbUser" = each.value.database_role } }
        }
      ] : [],
      each.key == "production" ? [
        {
          Sid       = "AllowLightsailServiceIdentity"
          Effect    = "Allow"
          Principal = { AWS = local.dsql_app_principal_arns[each.key] }
          Action    = "dsql:DbConnect"
          Resource  = aws_dsql_cluster.app[each.key].arn
          Condition = { StringEquals = { "dsql:DbUser" = each.value.database_role } }
        }
      ] : []
    )
  })
}

resource "aws_route53_record" "api" {
  for_each = local.environments
  zone_id  = data.aws_route53_zone.root.zone_id
  name     = local.api_hostnames[each.key]
  type     = "CNAME"
  ttl      = 60
  records  = [trimprefix(trimsuffix(aws_lightsail_container_service.api[each.key].url, "/"), "https://")]

  lifecycle {
    precondition {
      condition     = local.backend_images[each.key] != null
      error_message = "Set the same digest-pinned backend image for both environments before changing API DNS."
    }
  }

  depends_on = [aws_lightsail_container_service_deployment_version.api]
}

resource "aws_cloudfront_distribution" "app" {
  for_each            = local.frontend_environments
  enabled             = true
  comment             = "PawLocal ${each.key} full-stack app"
  default_root_object = "index.html"
  aliases             = ["${each.value.hostname}.${trimsuffix(var.root_domain, ".")}"]
  price_class         = "PriceClass_All"
  http_version        = "http2and3"
  is_ipv6_enabled     = true

  origin {
    domain_name              = aws_s3_bucket.frontend[each.key].bucket_regional_domain_name
    origin_id                = "pawlocal-${each.key}-private-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend[each.key].id
  }

  default_cache_behavior {
    target_origin_id       = "pawlocal-${each.key}-private-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD", "OPTIONS"]
    compress               = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa[each.key].arn
    }
    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    acm_certificate_arn      = var.cloudfront_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_cloudfront_function" "spa" {
  for_each = local.frontend_environments
  name     = "pawlocal-${each.key}-spa-routing"
  runtime  = "cloudfront-js-1.0"
  comment  = "Route frontend paths to the SPA entrypoint."
  publish  = true
  code = join("\r\n", [
    "function handler(event) {",
    "  var request = event.request;",
    "  if (request.uri === '/' || request.uri.indexOf('.') !== -1) return request;",
    "  request.uri = '/index.html';",
    "  return request;",
    "}",
    ""
  ])
}

data "aws_iam_policy_document" "frontend_bucket" {
  for_each = local.frontend_environments
  statement {
    sid    = "CloudFrontRead"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend[each.key].arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.app[each.key].arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  for_each = local.frontend_environments
  bucket   = aws_s3_bucket.frontend[each.key].id
  policy   = data.aws_iam_policy_document.frontend_bucket[each.key].json
}

resource "aws_route53_record" "frontend_a" {
  for_each = local.frontend_environments
  zone_id  = data.aws_route53_zone.root.zone_id
  name     = "${each.value.hostname}.${trimsuffix(var.root_domain, ".")}"
  type     = "A"
  alias {
    name                   = aws_cloudfront_distribution.app[each.key].domain_name
    zone_id                = aws_cloudfront_distribution.app[each.key].hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "frontend_aaaa" {
  for_each = local.frontend_environments
  zone_id  = data.aws_route53_zone.root.zone_id
  name     = "${each.value.hostname}.${trimsuffix(var.root_domain, ".")}"
  type     = "AAAA"
  alias {
    name                   = aws_cloudfront_distribution.app[each.key].domain_name
    zone_id                = aws_cloudfront_distribution.app[each.key].hosted_zone_id
    evaluate_target_health = false
  }
}

resource "random_id" "cognito_domain_suffix" {
  for_each    = local.environments
  byte_length = 3
}

resource "aws_cognito_user_pool" "app" {
  for_each = local.environments
  name     = "pawlocal-${each.key}"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  tags = local.common_tags
}

resource "aws_cognito_user_pool_domain" "app" {
  for_each     = local.environments
  domain       = "pawlocal-${each.key}-${random_id.cognito_domain_suffix[each.key].hex}"
  user_pool_id = aws_cognito_user_pool.app[each.key].id
}

resource "aws_cognito_user_pool_client" "app" {
  for_each     = local.environments
  name         = "pawlocal-${each.key}-browser"
  user_pool_id = aws_cognito_user_pool.app[each.key].id

  generate_secret                      = false
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://${each.value.hostname}.${trimsuffix(var.root_domain, ".")}/auth/callback"]
  logout_urls                          = ["https://${each.value.hostname}.${trimsuffix(var.root_domain, ".")}/"]
  access_token_validity                = 60
  refresh_token_validity               = 30
  id_token_validity                    = 60

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}



# This role can refresh the shared application's Terraform state and publish a
# deployment only to its matching container service. All infrastructure create,
# update, and delete permissions remain outside the release role.
# Keep the database-role mapping inputs visible in Terraform plans without
# executing SQL from a Terraform provisioner. An authorized local operator runs
# ops/bootstrap-development-dsql-role.ps1 after applying a reviewed dev plan.
resource "terraform_data" "app_dsql_role" {
  for_each = local.environments

  triggers_replace = [
    aws_dsql_cluster.app[each.key].arn,
    (trimspace(coalesce(local.dsql_app_principal_arns[each.key], "")) == "" ? "identity-pending" : local.dsql_app_principal_arns[each.key]),
    each.value.database_role,
    # Preserve the legacy marker fingerprints to avoid unrelated replacements.
    sha256(replace(replace(file("${path.module}/../../../backend/pawlocal/dsql_role_bootstrap.py"), "\r\n", "\n"), "\n", "\r\n")),
    filesha256("${path.module}/../../../backend/pawlocal/infrastructure/database.py"),
  ]

  lifecycle {
    ignore_changes = [triggers_replace[3], triggers_replace[4]]
  }
}

resource "aws_s3_bucket" "cloudtrail" {
  count         = var.enable_dsql_auth_event_capture ? 1 : 0
  bucket        = var.dsql_auth_audit_bucket_name
  force_destroy = false

  lifecycle {
    precondition {
      condition     = var.dsql_auth_audit_bucket_name != null && var.dsql_auth_audit_bucket_name != "" && var.dsql_auth_retention_days != null && var.dsql_auth_retention_days > 0
      error_message = "Set an owner-selected dsql_auth_audit_bucket_name and positive dsql_auth_retention_days when DSQL event capture is enabled."
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  count  = var.enable_dsql_auth_event_capture && var.dsql_auth_retention_days != null ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id

  rule {
    id     = "owner-selected-retention"
    status = "Enabled"
    filter {}

    expiration {
      days = var.dsql_auth_retention_days
    }
  }

}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  count                   = var.enable_dsql_auth_event_capture ? 1 : 0
  bucket                  = aws_s3_bucket.cloudtrail[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  count  = var.enable_dsql_auth_event_capture ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  count  = var.enable_dsql_auth_event_capture ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  policy = data.aws_iam_policy_document.cloudtrail_bucket[0].json
}

data "aws_iam_policy_document" "cloudtrail_bucket" {
  count = var.enable_dsql_auth_event_capture ? 1 : 0
  statement {
    sid       = "AWSCloudTrailAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail[0].arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
  }
  statement {
    sid       = "AWSCloudTrailWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail[0].arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_cloudtrail" "dsql_auth" {
  count                         = var.enable_dsql_auth_event_capture ? 1 : 0
  name                          = "pawlocal-dsql-authentication"
  s3_bucket_name                = aws_s3_bucket.cloudtrail[0].id
  include_global_service_events = false
  is_multi_region_trail         = false
  enable_logging                = true

  advanced_event_selector {
    name = "Aurora DSQL DbConnect only"
    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }
    field_selector {
      field  = "resources.type"
      equals = ["AWS::DSQL::Cluster"]
    }
    field_selector {
      field  = "resources.ARN"
      equals = [for env in keys(local.environments) : aws_dsql_cluster.app[env].arn]
    }
    field_selector {
      field  = "eventName"
      equals = ["DbConnect"]
    }
  }
  depends_on = [aws_s3_bucket_policy.cloudtrail]
}

resource "aws_cloudwatch_event_rule" "dsql_auth" {
  count       = var.enable_dsql_auth_event_capture && var.dsql_auth_alert_email != null ? 1 : 0
  name        = "pawlocal-dsql-auth-events"
  description = "Notify on Aurora DSQL application database connection events."
  event_pattern = jsonencode({
    source        = ["aws.dsql"]
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource   = ["dsql.amazonaws.com"]
      eventName     = ["DbConnect"]
      eventCategory = ["Data"]
    }
  })
}

resource "aws_sns_topic" "dsql_auth" {
  count = var.enable_dsql_auth_event_capture && var.dsql_auth_alert_email != null ? 1 : 0
  name  = "pawlocal-dsql-auth-events"
}

resource "aws_sns_topic_subscription" "dsql_auth_email" {
  count     = var.enable_dsql_auth_event_capture && var.dsql_auth_alert_email != null ? 1 : 0
  topic_arn = aws_sns_topic.dsql_auth[0].arn
  protocol  = "email"
  endpoint  = var.dsql_auth_alert_email
}

resource "aws_cloudwatch_event_target" "dsql_auth" {
  count     = var.enable_dsql_auth_event_capture && var.dsql_auth_alert_email != null ? 1 : 0
  rule      = aws_cloudwatch_event_rule.dsql_auth[0].name
  target_id = "pawlocal-dsql-auth-email"
  arn       = aws_sns_topic.dsql_auth[0].arn
}

resource "aws_sns_topic_policy" "dsql_auth" {
  count  = var.enable_dsql_auth_event_capture && var.dsql_auth_alert_email != null ? 1 : 0
  arn    = aws_sns_topic.dsql_auth[0].arn
  policy = data.aws_iam_policy_document.eventbridge_sns[0].json
}

data "aws_iam_policy_document" "eventbridge_sns" {
  count = var.enable_dsql_auth_event_capture && var.dsql_auth_alert_email != null ? 1 : 0
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.dsql_auth[0].arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.dsql_auth[0].arn]
    }
  }
}
