data "aws_route53_zone" "root" {
  name         = "${trimsuffix(var.root_domain, ".")}."
  private_zone = false
}

data "aws_caller_identity" "current" {}
locals {
  environments = var.environment_sizes
  frontend_environments = {
    development = var.environment_sizes.development
  }
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]

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
    environment = {
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
    }
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
}

resource "aws_dsql_cluster_policy" "api_connect" {
  for_each   = local.environments
  identifier = aws_dsql_cluster.app[each.key].identifier
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DelegateToAccountIdentities"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "dsql:DbConnectAdmin"
        Resource  = aws_dsql_cluster.app[each.key].arn
      },
      {
        Sid       = "AllowLightsailServiceIdentity"
        Effect    = "Allow"
        Principal = { AWS = aws_lightsail_container_service.api[each.key].principal_arn }
        Action    = "dsql:DbConnect"
        Resource  = aws_dsql_cluster.app[each.key].arn
        Condition = { StringEquals = { "dsql:DbUser" = each.value.database_role } }
      }
    ]
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
  code     = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri === '/' || request.uri.indexOf('.') !== -1) return request;
      request.uri = '/index.html';
      return request;
    }
  JS
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
  for_each           = local.frontend_environments
  name               = "pawlocal-${each.key}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_trust[each.key].json
}

data "aws_iam_policy_document" "github_deploy" {
  for_each = local.frontend_environments
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
  for_each = local.frontend_environments
  role     = aws_iam_role.github_deploy[each.key].id
  policy   = data.aws_iam_policy_document.github_deploy[each.key].json
}

# This role can refresh the shared application's Terraform state and publish a
# deployment only to its matching container service. All infrastructure create,
# update, and delete permissions remain outside the release role.
resource "aws_iam_role" "github_terraform_deploy" {
  for_each           = local.environments
  name               = "pawlocal-${each.key}-terraform-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_trust[each.key].json
  description        = "Terraform state-backed release deployment for the PawLocal ${each.key} Lightsail container service."
}

data "aws_iam_policy_document" "github_terraform_deploy" {
  for_each = local.environments

  statement {
    sid    = "ReadApplicationInfrastructureForTerraformRefresh"
    effect = "Allow"
    actions = [
      "acm:Describe*", "acm:List*",
      "cloudfront:Get*", "cloudfront:List*",
      "cognito-idp:Describe*", "cognito-idp:List*",
      "dsql:Get*", "dsql:List*",
      "events:Describe*", "events:List*",
      "iam:Get*", "iam:List*",
      "lightsail:GetContainerServices", "lightsail:GetContainerServiceDeployments",
      "lightsail:GetCertificates", "lightsail:GetDomains", "lightsail:GetInstances",
      "lightsail:GetStaticIps", "lightsail:GetContainerServicePowers",
      "lightsail:GetContainerServiceBundles",
      "route53:Get*", "route53:List*",
      "sns:Get*", "sns:List*",
      "cloudtrail:DescribeTrails", "cloudtrail:GetTrailStatus", "cloudtrail:ListTags",
      "tag:GetResources"
    ]
    resources = ["*"]
  }

  statement {
    sid     = "DescribePawLocalSpaFunctionsForTerraformRefresh"
    effect  = "Allow"
    actions = ["cloudfront:DescribeFunction"]
    resources = concat(
      [for function in values(aws_cloudfront_function.spa) : function.arn],
      ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-production-spa-routing"]
    )
  }

  statement {
    sid       = "ReadPawLocalUserPoolMfaForTerraformRefresh"
    effect    = "Allow"
    actions   = ["cognito-idp:GetUserPoolMfaConfig"]
    resources = [for user_pool in values(aws_cognito_user_pool.app) : user_pool.arn]
  }

  statement {
    sid    = "ReadPawLocalBucketConfiguration"
    effect = "Allow"
    actions = [
      "s3:GetBucket*", "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration", "s3:GetBucketPolicy",
      "s3:GetBucketOwnershipControls", "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketTagging", "s3:GetBucketVersioning", "s3:GetBucketLocation"
    ]
    resources = ["arn:aws:s3:::pawlocal-*"]
  }

  statement {
    sid       = "ListPawLocalFrontendBucketsForTerraformRefresh"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = concat([aws_s3_bucket.frontend["development"].arn], var.additional_frontend_bucket_arns)
  }

  statement {
    sid       = "ReadPawLocalFrontendBucketAccelerationForTerraformRefresh"
    effect    = "Allow"
    actions   = ["s3:GetAccelerateConfiguration"]
    resources = concat([aws_s3_bucket.frontend["development"].arn], var.additional_frontend_bucket_arns)
  }

  dynamic "statement" {
    for_each = each.key == "development" ? [true] : []

    content {
      sid       = "ReadPawLocalFrontendBucketReplicationForTerraformRefresh"
      effect    = "Allow"
      actions   = ["s3:GetReplicationConfiguration"]
      resources = concat([aws_s3_bucket.frontend["development"].arn], var.additional_frontend_bucket_arns)
    }
  }

  statement {
    sid    = "LockAndUpdateSharedTerraformState"
    effect = "Allow"
    actions = [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject"
    ]
    resources = [
      "arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate",
      "arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate.tflock"
    ]
  }

  statement {
    sid       = "ListSharedTerraformStatePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["pawlocal/terraform.tfstate", "pawlocal/terraform.tfstate.tflock"]
    }
  }

  statement {
    sid       = "ReadSharedTerraformStateBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
  }

  statement {
    sid       = "DeployOnlyThisContainerService"
    effect    = "Allow"
    actions   = ["lightsail:CreateContainerServiceDeployment"]
    resources = [aws_lightsail_container_service.api[each.key].arn]
  }
}

resource "aws_iam_role_policy" "github_terraform_deploy" {
  for_each = local.environments
  name     = "pawlocal-${each.key}-terraform-container-release"
  role     = aws_iam_role.github_terraform_deploy[each.key].id
  policy   = data.aws_iam_policy_document.github_terraform_deploy[each.key].json
}

# Aurora DSQL database roles and IAM mappings are SQL state rather than AWS API
# resources. terraform_data records the idempotent bootstrap operation in the
# same Terraform state; the helper uses the operator's short-lived AWS identity.
resource "terraform_data" "app_dsql_role" {
  for_each = local.environments

  triggers_replace = [
    aws_dsql_cluster.app[each.key].arn,
    aws_lightsail_container_service.api[each.key].principal_arn,
    each.value.database_role,
    # Keep the existing state fingerprint stable across Windows CRLF and Linux
    # LF checkouts. The role bootstrap is text; canonicalize it to CRLF before
    # hashing so the tracked operation does not rerun solely due to checkout EOLs.
    sha256(replace(replace(file("${path.module}/../../../backend/pawlocal/dsql_role_bootstrap.py"), "\r\n", "\n"), "\n", "\r\n")),
    filesha256("${path.module}/../../../backend/pawlocal/infrastructure/database.py"),
  ]

  lifecycle {
    # Keep the existing list position for state compatibility, but runtime
    # database-engine changes do not alter the SQL role bootstrap operation.
    ignore_changes = [triggers_replace[4]]
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../../../backend"
    interpreter = ["PowerShell", "-NoProfile", "-NonInteractive", "-Command"]
    command     = "& '${replace(var.dsql_bootstrap_python, "'", "''")}' -m pawlocal.dsql_role_bootstrap --endpoint '${aws_dsql_cluster.app[each.key].identifier}.dsql.${var.aws_region}.on.aws' --region '${var.aws_region}' --database-role '${each.value.database_role}' --iam-principal-arn '${aws_lightsail_container_service.api[each.key].principal_arn}' --legacy-iam-user-arn 'arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/pawlocal/pawlocal-${each.key}-dsql-app'; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
  }

  depends_on = [aws_dsql_cluster_policy.api_connect]
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
