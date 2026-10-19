data "aws_route53_zone" "site" {
  name         = trimsuffix(var.domain_name, ".")
  private_zone = false
}

locals {
  root_domain = trimsuffix(data.aws_route53_zone.site.name, ".")
  site_fqdn   = "${var.site_subdomain}.${local.root_domain}"
  name_prefix = "pawlocal-frontend"
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

module "fullstack" {
  source = "./fullstack"

  providers = {
    aws = aws.fullstack
  }

  aws_region                     = var.aws_region
  root_domain                    = var.domain_name
  cloudfront_certificate_arn     = var.certificate_arn
  backend_image_digests          = var.backend_image_digests
  dsql_bootstrap_python          = var.dsql_bootstrap_python
  enable_dsql_auth_event_capture = var.enable_dsql_auth_event_capture
  dsql_auth_audit_bucket_name    = var.dsql_auth_audit_bucket_name
  dsql_auth_retention_days       = var.dsql_auth_retention_days
  dsql_auth_alert_email          = var.dsql_auth_alert_email
}
