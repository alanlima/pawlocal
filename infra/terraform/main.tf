data "aws_route53_zone" "site" {
  name         = trimsuffix(var.domain_name, ".")
  private_zone = false
}

data "aws_caller_identity" "current" {}

locals {
  root_domain         = trimsuffix(data.aws_route53_zone.site.name, ".")
  site_fqdn           = "${var.site_subdomain}.${local.root_domain}"
  name_prefix         = "pawlocal-frontend"
  github_owner        = split("/", var.github_repository)[0]
  github_repo         = split("/", var.github_repository)[1]
  github_oidc_subject = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:ref:refs/heads/main"
  common_tags = {
    costcenter  = "personal"
    environment = var.environment
    managedby   = "terraform"
    project     = "pawlocal"
    component   = "frontend"
    workload    = "static-site"
  }
}

resource "random_id" "site_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "site" {
  bucket        = "${local.name_prefix}-${random_id.site_bucket_suffix.hex}"
  force_destroy = false
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.name_prefix}-oac"
  description                       = "Private S3 origin for the PawLocal frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "PawLocal static frontend"
  default_root_object = "index.html"
  aliases             = [local.site_fqdn]
  # PawLocal's initial audience is in Australia; PriceClass_All includes Australian edges.
  price_class     = "PriceClass_All"
  http_version    = "http2and3"
  is_ipv6_enabled = true

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "pawlocal-private-s3-origin"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "pawlocal-private-s3-origin"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD", "OPTIONS"]
    compress               = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.site_spa.arn
    }

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  depends_on = [
    aws_s3_bucket_public_access_block.site,
    module.fullstack,
  ]
}

resource "aws_cloudfront_function" "site_spa" {
  name    = "pawlocal-production-spa-routing"
  runtime = "cloudfront-js-1.0"
  comment = "Route frontend paths to the SPA entrypoint."
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
}

data "aws_iam_policy_document" "site_bucket" {
  statement {
    sid    = "AllowCloudFrontReadOnly"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.site]
}

resource "aws_route53_record" "site_a" {
  zone_id = data.aws_route53_zone.site.zone_id
  name    = local.site_fqdn
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "site_aaaa" {
  zone_id = data.aws_route53_zone.site.zone_id
  name    = local.site_fqdn
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.manage_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

moved {
  from = aws_iam_openid_connect_provider.github
  to   = aws_iam_openid_connect_provider.github[0]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.manage_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = var.manage_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "github_deploy_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        local.github_oidc_subject,
        "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:production"
      ]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "pawlocal-frontend-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_assume_role.json
  description        = "Allows PawLocal main-branch and production-environment workflows to publish frontend files and invalidate the existing CDN."
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "ListFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.site.arn]
  }

  statement {
    sid    = "PublishFrontendObjects"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["${aws_s3_bucket.site.arn}/*"]
  }

  statement {
    sid       = "InvalidateFrontendDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${aws_cloudfront_distribution.site.id}"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "pawlocal-frontend-publish"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

module "fullstack" {
  source = "./fullstack"

  providers = {
    aws = aws.fullstack
  }

  aws_region                      = var.aws_region
  root_domain                     = var.domain_name
  cloudfront_certificate_arn      = var.certificate_arn
  github_repository               = var.github_repository
  github_owner_id                 = var.github_owner_id
  github_repository_id            = var.github_repository_id
  terraform_state_bucket_name     = var.terraform_state_bucket_name
  additional_frontend_bucket_arns = [aws_s3_bucket.site.arn]
  # The existing root state owns the account-level provider; the child module reads it.
  manage_github_oidc_provider    = false
  backend_image_digests          = var.backend_image_digests
  enable_dsql_auth_event_capture = var.enable_dsql_auth_event_capture
  dsql_auth_audit_bucket_name    = var.dsql_auth_audit_bucket_name
  dsql_auth_retention_days       = var.dsql_auth_retention_days
  dsql_auth_alert_email          = var.dsql_auth_alert_email
}
