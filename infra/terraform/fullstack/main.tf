data "aws_route53_zone" "root" {
  name         = "${trimsuffix(var.root_domain, ".")}."
  private_zone = false
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  environments = var.environment_sizes
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]

  common_tags = {
    costcenter = "personal"
    managedby  = "terraform"
    project    = "pawlocal"
    component  = "fullstack-mvp"
    workload   = "application"
  }

  caddyfile = <<-CADDY
    {
      email {$ACME_EMAIL}
    }
    {$API_HOSTNAME} {
      encode zstd gzip
      reverse_proxy pawlocal-api:8000
    }
  CADDY

  instance_bootstrap = { for environment, config in local.environments : environment => templatefile("${path.module}/templates/bootstrap.sh.tftpl", {
    environment       = environment
    aws_region        = var.aws_region
    api_hostname      = "${config.api_name}.${trimsuffix(var.root_domain, ".")}"
    database_role     = config.database_role
    deploy_public_key = var.deploy_ssh_public_keys[environment]
  }) }
}

resource "random_id" "bucket_suffix" {
  for_each    = local.environments
  byte_length = 3
}

resource "aws_s3_bucket" "frontend" {
  for_each      = local.environments
  bucket        = "pawlocal-${each.key}-${random_id.bucket_suffix[each.key].hex}"
  force_destroy = false
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  for_each = local.environments
  bucket   = aws_s3_bucket.frontend[each.key].id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  for_each                = local.environments
  bucket                  = aws_s3_bucket.frontend[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  for_each = local.environments
  bucket   = aws_s3_bucket.frontend[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  for_each                          = local.environments
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

resource "aws_lightsail_instance" "api" {
  for_each          = local.environments
  name              = "pawlocal-${each.key}-api"
  availability_zone = data.aws_availability_zones.available.names[0]
  blueprint_id      = "amazon_linux_2023"
  bundle_id         = each.value.bundle_id
  user_data         = local.instance_bootstrap[each.key]

  lifecycle {
    precondition {
      condition     = contains(keys(var.deploy_ssh_public_keys), each.key)
      error_message = "A deployment public key is required for each environment."
    }
  }

  depends_on = [aws_dsql_cluster.app]
}

resource "aws_lightsail_static_ip" "api" {
  for_each = local.environments
  name     = "pawlocal-${each.key}-api-ip"
}

resource "aws_lightsail_static_ip_attachment" "api" {
  for_each       = local.environments
  static_ip_name = aws_lightsail_static_ip.api[each.key].name
  instance_name  = aws_lightsail_instance.api[each.key].name
}

resource "aws_lightsail_instance_public_ports" "api" {
  for_each      = local.environments
  instance_name = aws_lightsail_instance.api[each.key].name

  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
  }
  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
  }
  dynamic "port_info" {
    for_each = var.ssh_cidr_blocks
    content {
      protocol   = "tcp"
      from_port  = 22
      to_port    = 22
      cidrs      = [port_info.value]
      ipv6_cidrs = []
    }
  }
}

resource "aws_route53_record" "api" {
  for_each = local.environments
  zone_id  = data.aws_route53_zone.root.zone_id
  name     = "${each.value.api_name}.${trimsuffix(var.root_domain, ".")}"
  type     = "A"
  ttl      = 60
  records  = [aws_lightsail_static_ip.api[each.key].ip_address]
}

resource "aws_cloudfront_distribution" "app" {
  for_each            = local.environments
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

  origin {
    domain_name = "${each.value.api_name}.${trimsuffix(var.root_domain, ".")}."
    origin_id   = "pawlocal-${each.key}-api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
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

  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = "pawlocal-${each.key}-api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD", "OPTIONS"]
    compress               = true
    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Content-Type", "Origin", "Accept", "X-Request-ID"]
      cookies { forward = "all" }
    }
    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
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
  for_each = local.environments
  name     = "pawlocal-${each.key}-spa-routing"
  runtime  = "cloudfront-js-1.0"
  comment  = "Route frontend paths to the SPA entrypoint without rewriting API responses."
  publish  = true
  code     = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri.indexOf('/api/') === 0) return request;
      if (request.uri === '/' || request.uri.indexOf('.') !== -1) return request;
      request.uri = '/index.html';
      return request;
    }
  JS
}

data "aws_iam_policy_document" "frontend_bucket" {
  for_each = local.environments
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
  for_each = local.environments
  bucket   = aws_s3_bucket.frontend[each.key].id
  policy   = data.aws_iam_policy_document.frontend_bucket[each.key].json
}

resource "aws_route53_record" "frontend_a" {
  for_each = local.environments
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
  for_each = local.environments
  zone_id  = data.aws_route53_zone.root.zone_id
  name     = "${each.value.hostname}.${trimsuffix(var.root_domain, ".")}"
  type     = "AAAA"
  alias {
    name                   = aws_cloudfront_distribution.app[each.key].domain_name
    zone_id                = aws_cloudfront_distribution.app[each.key].hosted_zone_id
    evaluate_target_health = false
  }
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.manage_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.manage_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  oidc_provider_arn = var.manage_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "github_deploy_trust" {
  for_each = local.environments
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:${each.key}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  for_each           = local.environments
  name               = "pawlocal-${each.key}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_trust[each.key].json
}

data "aws_iam_policy_document" "github_deploy" {
  for_each = local.environments
  statement {
    sid       = "ListFrontendBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.frontend[each.key].arn]
  }
  statement {
    sid       = "PublishFrontend"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.frontend[each.key].arn}/*"]
  }
  statement {
    sid       = "InvalidateFrontendDistribution"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${aws_cloudfront_distribution.app[each.key].id}"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  for_each = local.environments
  role     = aws_iam_role.github_deploy[each.key].id
  policy   = data.aws_iam_policy_document.github_deploy[each.key].json
}

resource "aws_iam_user" "app" {
  for_each = local.environments
  name     = "pawlocal-${each.key}-dsql-app"
  path     = "/pawlocal/"
}

data "aws_iam_policy_document" "app_dsql_connect" {
  for_each = local.environments
  statement {
    sid       = "ConnectAsApplicationRole"
    actions   = ["dsql:DbConnect"]
    resources = [aws_dsql_cluster.app[each.key].arn]
    condition {
      test     = "StringEquals"
      variable = "dsql:DbUser"
      values   = [local.environments[each.key].database_role]
    }
  }
}

resource "aws_iam_user_policy" "app_dsql_connect" {
  for_each = local.environments
  user     = aws_iam_user.app[each.key].name
  policy   = data.aws_iam_policy_document.app_dsql_connect[each.key].json
}

resource "aws_s3_bucket" "cloudtrail" {
  count         = var.enable_dsql_auth_event_capture ? 1 : 0
  bucket        = "pawlocal-dsql-audit-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  force_destroy = false
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
