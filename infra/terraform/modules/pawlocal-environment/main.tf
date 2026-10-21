data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  frontend_label = var.environment == "development" ? "pawlocal-dev" : "pawlocal"
  api_label      = var.environment == "development" ? "api-dev" : "api"
  database_role  = "pawlocal_${var.environment}_app"

  frontend_hostname = "${local.frontend_label}.${trimsuffix(var.root_domain, ".")}"
  api_hostname      = "${local.api_label}.${trimsuffix(var.root_domain, ".")}"
  service_name      = "pawlocal-${var.environment}-api"
  certificate_name  = "pawlocal-${var.environment}-api"
  common_tags = {
    project     = "pawlocal"
    environment = var.environment
    managedby   = "terraform"
    component   = "fullstack-mvp"
    workload    = "application"
    costcenter  = "personal"
  }
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

resource "aws_s3_bucket" "frontend" {
  bucket        = "pawlocal-${var.environment}-${random_id.bucket_suffix.hex}"
  force_destroy = false
  tags          = local.common_tags
  depends_on    = [time_sleep.application_permissions_propagation]
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
  deletion_protection_enabled = true
  force_destroy               = false
  kms_encryption_key          = "AWS_OWNED_KMS_KEY"
  tags                        = merge(local.common_tags, { Name = "pawlocal-${var.environment}", purpose = "pawlocal-app-database" })
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

resource "aws_lightsail_certificate" "api" {
  name        = local.certificate_name
  domain_name = local.api_hostname
  tags        = local.common_tags
  depends_on  = [time_sleep.application_permissions_propagation]
}

resource "aws_route53_record" "api_certificate_validation" {
  zone_id = var.route53_zone_id
  name    = one(aws_lightsail_certificate.api.domain_validation_options).resource_record_name
  type    = one(aws_lightsail_certificate.api.domain_validation_options).resource_record_type
  records = [one(aws_lightsail_certificate.api.domain_validation_options).resource_record_value]
  ttl     = 60
}

resource "aws_lightsail_container_service" "api" {
  name        = local.service_name
  power       = var.container_power
  scale       = var.container_scale
  is_disabled = false
  tags        = local.common_tags

  public_domain_names {
    certificate {
      certificate_name = aws_lightsail_certificate.api.name
      domain_names     = [local.api_hostname]
    }
  }

  depends_on = [aws_route53_record.api_certificate_validation]
}

resource "aws_lightsail_container_service_deployment_version" "api" {
  count        = local.deployment_enabled ? 1 : 0
  service_name = aws_lightsail_container_service.api.name

  container {
    container_name = "pawlocal-api"
    image          = var.backend_image
    environment = {
      AWS_REGION                     = var.aws_region
      PAWLOCAL_RELEASE_ENVIRONMENT   = var.environment
      PAWLOCAL_RELEASE_IMAGE_DIGEST  = split("@", var.backend_image)[1]
      PAWLOCAL_DATABASE_PROVIDER     = "aurora_dsql"
      PAWLOCAL_DATABASE_URL          = "auroradsql+psycopg://${local.database_role}@${aws_dsql_cluster.application.identifier}.dsql.${var.aws_region}.on.aws/postgres?application_name=pawlocal-${var.environment}"
      PAWLOCAL_DSQL_ASSUME_ROLE_ARN  = var.runtime_role_arn
      PAWLOCAL_COGNITO_ISSUER        = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.application.id}"
      PAWLOCAL_COGNITO_APP_CLIENT_ID = aws_cognito_user_pool_client.browser.id
      PAWLOCAL_CORS_ORIGINS          = jsonencode(["https://${local.frontend_hostname}"])
      PAWLOCAL_TELEMETRY_ENABLED     = "false"
      OTEL_SDK_DISABLED              = "true"
    }
    ports = { "8000" = "HTTP" }
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

  depends_on = [aws_dsql_cluster_policy.application]
}

resource "aws_route53_record" "api" {
  count      = local.deployment_enabled ? 1 : 0
  zone_id    = var.route53_zone_id
  name       = local.api_hostname
  type       = "CNAME"
  ttl        = 60
  records    = [trimprefix(trimsuffix(aws_lightsail_container_service.api.url, "/"), "https://")]
  depends_on = [aws_lightsail_container_service_deployment_version.api]
}

resource "aws_cognito_user_pool" "application" {
  name                     = "pawlocal-${var.environment}"
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
  tags       = local.common_tags
  depends_on = [time_sleep.application_permissions_propagation]
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
