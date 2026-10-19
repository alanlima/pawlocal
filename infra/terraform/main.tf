# Legacy single-state migration source for Issue #81.
# The old root and both destination roots must be frozen while these removals
# and the corresponding generated import blocks are reviewed and applied.
locals {
  common_tags = {
    costcenter  = "personal"
    environment = var.environment
    managedby   = "terraform"
    project     = "pawlocal"
    component   = "frontend"
    workload    = "static-site"
  }
}

removed {
  from = random_id.site_bucket_suffix
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_bucket.site
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_bucket_ownership_controls.site
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_bucket_public_access_block.site
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_bucket_server_side_encryption_configuration.site
  lifecycle { destroy = false }
}

removed {
  from = aws_cloudfront_origin_access_control.site
  lifecycle { destroy = false }
}

removed {
  from = aws_cloudfront_distribution.site
  lifecycle { destroy = false }
}

removed {
  from = aws_cloudfront_function.site_spa
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_bucket_policy.site
  lifecycle { destroy = false }
}

removed {
  from = aws_route53_record.site_a
  lifecycle { destroy = false }
}

removed {
  from = aws_route53_record.site_aaaa
  lifecycle { destroy = false }
}

removed {
  from = aws_iam_openid_connect_provider.github
  lifecycle { destroy = false }
}

removed {
  from = aws_iam_role.github_deploy
  lifecycle { destroy = false }
}

removed {
  from = aws_iam_role_policy.github_deploy
  lifecycle { destroy = false }
}

# The module removal covers all 27 app-managed instances and 1 data source in
# module.fullstack. The destination app root retains all 27 managed addresses.
removed {
  from = module.fullstack
  lifecycle { destroy = false }
}
