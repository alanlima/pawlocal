data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  frontend_label = var.environment == "development" ? "pawlocal-dev" : "pawlocal"
  database_role  = "pawlocal_${var.environment}_app"

  resource_name_prefix = "pawlocal-${var.environment}"
  resource_suffixes = {
    container_service = "api"
  }
  resource_names = {
    container_service = "${local.resource_name_prefix}-${local.resource_suffixes.container_service}"
  }

  cognito_pre_sign_up_name             = "${local.resource_name_prefix}-cognito-pre-signup"
  default_cognito_pre_sign_up_role_arn = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${local.cognito_pre_sign_up_name}"
  cognito_pre_sign_up_role_arn         = coalesce(var.cognito_pre_sign_up_role_arn, local.default_cognito_pre_sign_up_role_arn)

  frontend_hostname = "${local.frontend_label}.${trimsuffix(var.root_domain, ".")}"
  # Certificate identity/creation input only; never published as an API endpoint.
  legacy_certificate_domain = "${var.environment == "development" ? "api-dev" : "api"}.${trimsuffix(var.root_domain, ".")}"
  common_tags = {
    project     = var.project_name
    environment = var.environment
    managedby   = "terraform"
    component   = "fullstack-mvp"
    workload    = "application"
    costcenter  = "personal"
  }
  dsql_tags = merge(local.common_tags, {
    Name    = "pawlocal-${var.environment}"
    purpose = "pawlocal-app-database"
  })
  dsql_setup_revision          = "dsql-setup-v1-dsql_0001_initial"
  deployment_enabled           = var.backend_image != "" && var.runtime_role_arn != ""
  iam_managed_policy_max_bytes = 6144
}

resource "random_id" "bucket_suffix" {
  byte_length = 3
}

resource "random_id" "cognito_domain_suffix" {
  byte_length = 3
}

resource "aws_iam_policy" "application" {
  name        = "pawlocal-${var.environment}-application"
  description = "Environment-owned application permissions for PawLocal ${var.environment}."
  policy      = data.aws_iam_policy_document.application.json
  tags        = local.common_tags

  lifecycle {
    precondition {
      condition     = length(data.aws_iam_policy_document.application.minified_json) <= local.iam_managed_policy_max_bytes
      error_message = "The environment application policy is ${length(data.aws_iam_policy_document.application.minified_json)} bytes; it must stay within IAM's 6144-byte managed-policy limit."
    }
  }
}

resource "aws_iam_role_policy_attachment" "application" {
  role       = var.terraform_apply_role_name
  policy_arn = aws_iam_policy.application.arn
}

resource "time_sleep" "application_permissions_propagation" {
  create_duration = "30s"
  triggers = {
    application_policy_sha256 = sha256(data.aws_iam_policy_document.application.json)
  }
  depends_on = [aws_iam_role_policy_attachment.application]
}

resource "aws_iam_policy" "frontend_publish" {
  name        = "pawlocal-${var.environment}-frontend-publish"
  description = "Environment-owned frontend publication permissions for PawLocal ${var.environment}."
  policy      = data.aws_iam_policy_document.frontend_publish.json
  tags        = local.common_tags
}

resource "aws_iam_role_policy_attachment" "frontend_publish" {
  role       = var.frontend_publish_role_name
  policy_arn = aws_iam_policy.frontend_publish.arn
}

data "aws_iam_policy_document" "frontend_teardown" {
  count = var.teardown_enabled ? 1 : 0

  statement {
    sid       = "DeleteOnlyMatchingFrontendObjects"
    effect    = "Allow"
    actions   = ["s3:DeleteObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*/*"]
  }
}

resource "aws_iam_policy" "frontend_teardown" {
  count       = var.teardown_enabled ? 1 : 0
  name        = "pawlocal-${var.environment}-frontend-teardown"
  description = "Temporary object deletion permission for reviewed PawLocal ${var.environment} teardown."
  policy      = data.aws_iam_policy_document.frontend_teardown[0].json
  tags        = local.common_tags
}

# Attach the exact cleanup policy to the bounded Terraform identity only while
# protected teardown mode is enabled, so force_destroy can empty the bucket.
resource "aws_iam_role_policy_attachment" "frontend_teardown" {
  count      = var.teardown_enabled ? 1 : 0
  role       = var.terraform_apply_role_name
  policy_arn = aws_iam_policy.frontend_teardown[0].arn
}

resource "aws_iam_policy" "runtime" {
  count       = var.runtime_role_arn == "" ? 0 : 1
  name        = "pawlocal-${var.environment}-runtime"
  description = "Environment-owned DSQL connection permission for PawLocal ${var.environment}."
  policy      = data.aws_iam_policy_document.runtime[0].json
  tags        = local.common_tags
}

resource "aws_iam_role_policy_attachment" "runtime" {
  count      = var.runtime_role_arn == "" ? 0 : 1
  role       = "pawlocal-${var.environment}-dsql-runtime"
  policy_arn = aws_iam_policy.runtime[0].arn
}

resource "aws_iam_policy" "dsql_setup" {
  count       = var.runtime_role_arn == "" ? 0 : 1
  name        = "pawlocal-${var.environment}-dsql-setup"
  description = "Exact DSQL post-apply permissions for PawLocal ${var.environment}."
  policy      = data.aws_iam_policy_document.dsql_setup[0].json
  tags        = local.common_tags
}

resource "aws_iam_role_policy_attachment" "dsql_setup" {
  count      = var.runtime_role_arn == "" ? 0 : 1
  role       = var.terraform_apply_role_name
  policy_arn = aws_iam_policy.dsql_setup[0].arn
}

resource "aws_s3_bucket" "frontend" {
  bucket        = "pawlocal-${var.environment}-${random_id.bucket_suffix.hex}"
  force_destroy = var.teardown_enabled
  tags          = local.common_tags
  depends_on = [
    time_sleep.application_permissions_propagation,
    aws_iam_role_policy_attachment.frontend_teardown,
  ]
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "pawlocal-${var.environment}-frontend-oac"
  description                       = "Private S3 origin for PawLocal ${var.environment}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
  depends_on                        = [time_sleep.application_permissions_propagation]
}

resource "aws_cloudfront_function" "spa" {
  name    = "pawlocal-${var.environment}-spa-routing"
  runtime = "cloudfront-js-1.0"
  comment = "Route PawLocal ${var.environment} frontend paths to the SPA entrypoint."
  publish = true
  code = join("\r\n", [
    "function handler(event) {",
    "  var request = event.request;",
    "  if (request.uri === '/' || request.uri.indexOf('.') !== -1) return request;",
    "  request.uri = '/index.html';",
    "  return request;",
    "}",
    ""
  ])
  depends_on = [time_sleep.application_permissions_propagation]
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  comment             = "PawLocal ${var.environment} full-stack frontend"
  default_root_object = "index.html"
  aliases             = [local.frontend_hostname]
  price_class         = "PriceClass_All"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  tags                = local.common_tags

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "pawlocal-${var.environment}-private-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # AWS managed policies have stable IDs; no new IAM policy-lookup authority.
  # CachingDisabled + AllViewerExceptHostHeader forwards Authorization, trace
  # headers, cookies and queries, while TLS and Host use the Lightsail hostname.
  origin {
    domain_name = trimprefix(trimsuffix(aws_lightsail_container_service.api.url, "/"), "https://")
    origin_id   = "pawlocal-${var.environment}-api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = ["/api", "/api/*"]
    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "pawlocal-${var.environment}-api"
      viewer_protocol_policy   = "https-only"
      allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods           = ["GET", "HEAD"]
      cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
      origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
      compress                 = true
    }
  }

  # Error TTL is distribution-wide. Preserve origin status/body (no SPA error
  # mapping), and never conceal API health failures or recovery behind a cache.
  dynamic "custom_error_response" {
    for_each = toset([400, 403, 404, 405, 414, 416, 500, 501, 502, 503, 504])
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }

  default_cache_behavior {
    target_origin_id       = "pawlocal-${var.environment}-private-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD", "OPTIONS"]
    compress               = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa.arn
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

  depends_on = [time_sleep.application_permissions_propagation]
}

data "aws_iam_policy_document" "frontend_bucket" {
  statement {
    sid    = "CloudFrontRead"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket.json
}

resource "aws_route53_record" "frontend_a" {
  zone_id = var.route53_zone_id
  name    = local.frontend_hostname
  type    = "A"
  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "frontend_aaaa" {
  zone_id = var.route53_zone_id
  name    = local.frontend_hostname
  type    = "AAAA"
  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_dsql_cluster" "application" {
  deletion_protection_enabled = !var.teardown_enabled
  force_destroy               = var.teardown_enabled
  kms_encryption_key          = "AWS_OWNED_KMS_KEY"
  tags                        = local.dsql_tags
  depends_on                  = [time_sleep.application_permissions_propagation]
}

resource "aws_dsql_cluster_policy" "application" {
  count      = var.runtime_role_arn == "" ? 0 : 1
  identifier = aws_dsql_cluster.application.identifier
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowExactEnvironmentRuntimeRole"
      Effect    = "Allow"
      Principal = { AWS = var.runtime_role_arn }
      Action    = "dsql:DbConnect"
      Resource  = aws_dsql_cluster.application.arn
      Condition = { StringEquals = { "dsql:DbUser" = local.database_role } }
    }]
  })
}

resource "time_sleep" "dsql_setup_permissions_propagation" {
  count           = var.runtime_role_arn == "" ? 0 : 1
  create_duration = "30s"
  triggers = {
    setup_policy_sha256   = sha256(data.aws_iam_policy_document.dsql_setup[0].json)
    cluster_policy_sha256 = sha256(aws_dsql_cluster_policy.application[0].policy)
  }
  depends_on = [
    aws_iam_role_policy_attachment.dsql_setup,
    aws_iam_role_policy_attachment.runtime,
  ]
}

module "dsql_post_apply_setup" {
  count  = var.runtime_role_arn == "" ? 0 : 1
  source = "../dsql-post-apply-setup"

  cluster_identity  = aws_dsql_cluster.application.arn
  runtime_identity  = var.runtime_role_arn
  setup_revision    = local.dsql_setup_revision
  command           = "python -m pawlocal.dsql_post_apply_setup"
  working_directory = abspath("${path.module}/../../../..")
  environment = {
    PYTHONPATH                           = abspath("${path.module}/../../../../backend")
    PAWLOCAL_DSQL_SETUP_ENVIRONMENT      = var.environment
    PAWLOCAL_DSQL_SETUP_ENDPOINT         = "${aws_dsql_cluster.application.identifier}.dsql.${var.aws_region}.on.aws"
    PAWLOCAL_DSQL_SETUP_REGION           = var.aws_region
    PAWLOCAL_DSQL_SETUP_DATABASE_ROLE    = local.database_role
    PAWLOCAL_DSQL_SETUP_RUNTIME_ROLE_ARN = var.runtime_role_arn
  }

  depends_on = [
    aws_dsql_cluster_policy.application,
    time_sleep.dsql_setup_permissions_propagation,
  ]
}

# Keep the original address/name and valid creation inputs in every mode.
# Detachment changes only the service association, never certificate ownership.
resource "aws_lightsail_certificate" "api" {
  name        = "${local.resource_names.container_service}-cert"
  domain_name = local.legacy_certificate_domain
  tags        = local.common_tags
  depends_on  = [time_sleep.application_permissions_propagation]

  lifecycle {
    prevent_destroy = true
  }
}

# Retain the original validation record identity for issuance and renewal.
# This CNAME validates the certificate; it does not route API requests.
resource "aws_route53_record" "api_certificate_validation" {
  zone_id = var.route53_zone_id
  name    = one(aws_lightsail_certificate.api.domain_validation_options).resource_record_name
  type    = one(aws_lightsail_certificate.api.domain_validation_options).resource_record_type
  records = [one(aws_lightsail_certificate.api.domain_validation_options).resource_record_value]
  ttl     = 60
}

resource "aws_lightsail_container_service" "api" {
  name        = local.resource_names.container_service
  power       = var.container_power
  scale       = var.container_scale
  is_disabled = false
  tags        = local.common_tags

  dynamic "public_domain_names" {
    for_each = var.detach_lightsail_certificate ? [] : [true]
    content {
      certificate {
        certificate_name = aws_lightsail_certificate.api.name
        domain_names     = [local.legacy_certificate_domain]
      }
    }
  }

  depends_on = [time_sleep.application_permissions_propagation, aws_route53_record.api_certificate_validation]
}

locals {
  backend_runtime_environment = local.deployment_enabled ? {
    AWS_REGION                        = var.aws_region
    PAWLOCAL_RELEASE_ENVIRONMENT      = var.environment
    PAWLOCAL_RELEASE_IMAGE_DIGEST     = split("@", var.backend_image)[1]
    PAWLOCAL_DATABASE_PROVIDER        = "aurora_dsql"
    PAWLOCAL_DATABASE_URL             = "auroradsql+psycopg://${local.database_role}@${aws_dsql_cluster.application.identifier}.dsql.${var.aws_region}.on.aws/postgres?application_name=pawlocal-${var.environment}"
    PAWLOCAL_DSQL_ASSUME_ROLE_ARN     = var.runtime_role_arn
    PAWLOCAL_COGNITO_ISSUER           = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.application.id}"
    PAWLOCAL_COGNITO_APP_CLIENT_ID    = aws_cognito_user_pool_client.browser.id
    PAWLOCAL_CORS_ORIGINS             = jsonencode(["https://${local.frontend_hostname}"])
    PAWLOCAL_TELEMETRY_ENABLED        = tostring(local.hosted_telemetry_enabled)
    OTEL_SDK_DISABLED                 = tostring(!local.hosted_telemetry_enabled)
    OTEL_EXPORTER_OTLP_ENDPOINT       = local.hosted_telemetry_enabled ? try(coalesce(local.hosted_otlp_endpoint), "") : ""
    PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID = local.hosted_telemetry_enabled ? try(coalesce(local.hosted_otlp_instance_id), "") : ""
  } : {}
}

resource "aws_lightsail_container_service_deployment_version" "api" {
  count        = local.deployment_enabled ? 1 : 0
  service_name = aws_lightsail_container_service.api.name

  container {
    container_name = "pawlocal-api"
    image          = var.backend_image
    environment    = local.backend_runtime_environment
    ports          = { "8000" = "HTTP" }
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

  depends_on = [module.dsql_post_apply_setup]
}

module "cognito_pre_sign_up" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "= 8.12.0"

  providers = {
    aws = aws.cognito_deployment
  }

  function_name = local.cognito_pre_sign_up_name
  description   = "Confirm PawLocal ${var.environment} self-service Cognito sign-ups."
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  timeout       = 3
  memory_size   = 128

  create_role = false
  lambda_role = local.cognito_pre_sign_up_role_arn

  source_path                  = "${path.module}/lambda/cognito-pre-signup/index.mjs"
  artifacts_dir                = "${path.root}/.terraform/lambda-builds"
  recreate_missing_package     = true
  trigger_on_package_timestamp = false
  # The content-derived filename owns code changes. Rebuilding local packaging
  # sidecars must not make source_code_hash unknown and update unchanged code.
  ignore_source_code_hash = true

  cloudwatch_logs_retention_in_days = 30
  create_sam_metadata               = false
  allowed_triggers                  = {}
  tags                              = local.common_tags

  depends_on = [time_sleep.application_permissions_propagation]
}

resource "aws_cognito_user_pool" "application" {
  name = "${var.project_name}-${var.environment}"

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  lambda_config {
    pre_sign_up = module.cognito_pre_sign_up.lambda_function_arn
  }

  mfa_configuration = "OFF"

  password_policy {
    minimum_length                   = var.cognito_password_policy.minimum_length
    require_lowercase                = var.cognito_password_policy.require_lowercase
    require_numbers                  = var.cognito_password_policy.require_numbers
    require_symbols                  = false
    require_uppercase                = var.cognito_password_policy.require_uppercase
    temporary_password_validity_days = 7
  }

  schema {
    attribute_data_type = "String"
    mutable             = true
    name                = "name"
    required            = true
  }

  username_configuration {
    case_sensitive = false
  }

  tags       = local.common_tags
  depends_on = [time_sleep.application_permissions_propagation]
}

resource "aws_lambda_permission" "allow_cognito_pre_sign_up" {
  provider       = aws.cognito_deployment
  statement_id   = "AllowCognitoPreSignUp"
  action         = "lambda:InvokeFunction"
  function_name  = module.cognito_pre_sign_up.lambda_function_name
  principal      = "cognito-idp.amazonaws.com"
  source_arn     = aws_cognito_user_pool.application.arn
  source_account = data.aws_caller_identity.current.account_id

  lifecycle {
    precondition {
      condition     = var.cognito_pre_sign_up_role_arn == null || var.cognito_pre_sign_up_role_arn == local.default_cognito_pre_sign_up_role_arn
      error_message = "cognito_pre_sign_up_role_arn must match the current partition, account, environment, and exact pre sign-up role name."
    }
  }
}

resource "aws_cognito_user_pool_domain" "application" {
  domain       = "pawlocal-${var.environment}-${random_id.cognito_domain_suffix.hex}"
  user_pool_id = aws_cognito_user_pool.application.id
}

resource "aws_cognito_user_pool_client" "browser" {
  name                                 = "pawlocal-${var.environment}-browser"
  user_pool_id                         = aws_cognito_user_pool.application.id
  generate_secret                      = false
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://${local.frontend_hostname}/auth/callback"]
  logout_urls                          = ["https://${local.frontend_hostname}/"]
  access_token_validity                = 60
  refresh_token_validity               = 30
  id_token_validity                    = 60
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
