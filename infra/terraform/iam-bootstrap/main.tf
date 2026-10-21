data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "aws_iam_openid_connect_provider" "github" {
  count = var.manage_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  plan_transfer_bucket_name = "pawlocal-terraform-plans-${data.aws_caller_identity.current.account_id}"
  plan_transfer_bucket_arn  = "arn:${data.aws_partition.current.partition}:s3:::${local.plan_transfer_bucket_name}"
}

resource "aws_s3_bucket" "plan_transfer" {
  bucket        = local.plan_transfer_bucket_name
  force_destroy = false
  tags = {
    project   = "pawlocal"
    managedby = "terraform"
    purpose   = "short-lived-terraform-plan-transfer"
  }
}

resource "aws_s3_bucket_public_access_block" "plan_transfer" {
  bucket                  = aws_s3_bucket.plan_transfer.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "plan_transfer" {
  bucket = aws_s3_bucket.plan_transfer.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "plan_transfer_tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [local.plan_transfer_bucket_arn, "${local.plan_transfer_bucket_arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "plan_transfer_tls_only" {
  bucket = aws_s3_bucket.plan_transfer.id
  policy = data.aws_iam_policy_document.plan_transfer_tls_only.json
}

resource "aws_s3_bucket_server_side_encryption_configuration" "plan_transfer" {
  bucket = aws_s3_bucket.plan_transfer.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_versioning" "plan_transfer" {
  bucket = aws_s3_bucket.plan_transfer.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "plan_transfer" {
  bucket = aws_s3_bucket.plan_transfer.id
  rule {
    id     = "expire-sensitive-plan-artifacts"
    status = "Enabled"
    filter { prefix = "plans/" }
    expiration { days = 1 }
    noncurrent_version_expiration { noncurrent_days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.manage_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]
  oidc_arn     = var.manage_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
  environments = {
    development = {
      state_key = "pawlocal/development/terraform.tfstate"
      api_name  = "api-dev"
      frontend  = "pawlocal-dev"
    }
    production = {
      state_key = "pawlocal/production/terraform.tfstate"
      api_name  = "api"
      frontend  = "pawlocal"
    }
  }
  role_definitions = merge(
    { for env, _ in local.environments : "${env}-plan" => { environment = env, purpose = "plan", role_name = "pawlocal-${env}-terraform-plan", subject_environment = "${env}-plan" } },
    { for env, _ in local.environments : "${env}-apply" => { environment = env, purpose = "apply", role_name = "pawlocal-${env}-terraform-apply", subject_environment = "${env}-apply" } }
  )
  readonly_discovery_actions = [
    "acm:DescribeCertificate", "acm:ListCertificates",
    "cloudfront:ListDistributions", "cloudfront:ListFunctions",
    "cognito-idp:ListUserPools", "dsql:ListClusters",
    "iam:GetRole", "iam:GetRolePolicy", "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListRoles", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListPolicyVersions",
    "lightsail:GetContainerServices", "lightsail:GetContainerServiceDeployments", "lightsail:GetCertificates", "lightsail:GetOperations", "lightsail:GetDomains", "lightsail:GetContainerServicePowers", "lightsail:GetContainerServiceBundles",
    "route53:ListHostedZonesByName", "route53:GetChange",
    "sts:GetCallerIdentity", "tag:GetResources"
  ]
  regional_read_actions = [
    "acm:DescribeCertificate",
    "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:GetFunction", "cloudfront:GetOriginAccessControl", "cloudfront:ListTagsForResource",
    "cognito-idp:DescribeUserPool", "cognito-idp:DescribeUserPoolClient", "cognito-idp:DescribeUserPoolDomain", "cognito-idp:GetUserPoolMfaConfig", "cognito-idp:ListTagsForResource",
    "dsql:GetCluster", "dsql:GetClusterPolicy", "dsql:GetVpcEndpointServiceName", "dsql:ListTagsForResource",
    "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
    "lightsail:GetContainerServices", "lightsail:GetContainerServiceDeployments", "lightsail:GetCertificates", "lightsail:GetOperation",
    "route53:GetHostedZone", "route53:ListResourceRecordSets"
  ]
  app_resource_tags = {
    "aws:ResourceTag/project" = "pawlocal"
  }
  env_tag = {
    "aws:ResourceTag/project" = "pawlocal"
  }
}

data "aws_iam_policy_document" "role_trust" {
  for_each = local.role_definitions

  statement {
    sid     = "ExactPawLocalGitHubEnvironment"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:${each.value.subject_environment}"]
    }
  }
}

resource "aws_iam_role" "github_terraform" {
  for_each = local.role_definitions

  name                 = each.value.role_name
  assume_role_policy   = data.aws_iam_policy_document.role_trust[each.key].json
  description          = "PawLocal Terraform ${each.value.purpose} role for ${each.value.environment}."
  permissions_boundary = each.value.purpose == "apply" ? aws_iam_policy.environment_apply_boundary[each.value.environment].arn : null
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = each.value.environment
    managedby   = "terraform"
    purpose     = each.value.purpose
  }
}

data "aws_iam_policy_document" "role_permissions" {
  for_each = local.role_definitions

  statement {
    sid    = "ReadStateAndLockOnlyTheAssignedKey"
    effect = "Allow"
    actions = each.value.purpose == "plan" ? [
      "s3:GetObject"
      ] : [
      "s3:GetObject", "s3:PutObject"
    ]
    resources = [
      "arn:aws:s3:::${var.terraform_state_bucket_name}/${local.environments[each.value.environment].state_key}",
      "arn:aws:s3:::${var.terraform_state_bucket_name}/${local.environments[each.value.environment].state_key}.tflock"
    ]
  }

  statement {
    sid       = "AcquireAndReleaseOnlyTheAssignedStateLock"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}/${local.environments[each.value.environment].state_key}.tflock"]
  }

  statement {
    sid       = "ListOnlyTheAssignedStatePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        local.environments[each.value.environment].state_key,
        "${local.environments[each.value.environment].state_key}.tflock"
      ]
    }
  }

  statement {
    sid       = "ReadStateBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
  }

  dynamic "statement" {
    for_each = each.value.purpose == "plan" ? [true] : []
    content {
      sid       = "UploadOnlyOwnEnvironmentPlan"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = ["${local.plan_transfer_bucket_arn}/plans/${each.value.environment}/*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ReadOnlyOwnEnvironmentPlan"
      effect    = "Allow"
      actions   = ["s3:GetObject"]
      resources = ["${local.plan_transfer_bucket_arn}/plans/${each.value.environment}/*"]
    }
  }

  statement {
    sid    = "ReadOnlyProviderDiscovery"
    effect = "Allow"
    actions = each.value.purpose == "plan" ? [
      for action in local.readonly_discovery_actions : action
      if !startswith(action, "iam:") || action == "iam:ListRoles"
    ] : local.readonly_discovery_actions
    resources = ["*"]
  }

  statement {
    sid    = "ReadApplicationResources"
    effect = "Allow"
    actions = each.value.purpose == "plan" ? [
      for action in local.regional_read_actions : action
      if !startswith(action, "iam:")
    ] : local.regional_read_actions
    resources = ["*"]
  }

  statement {
    sid       = "ReadMatchingEnvironmentFrontendBucketForRefresh"
    effect    = "Allow"
    actions   = ["s3:GetAccelerateConfiguration", "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketLocation", "s3:GetBucketLogging", "s3:GetBucketObjectLockConfiguration", "s3:GetBucketOwnershipControls", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketRequestPayment", "s3:GetBucketTagging", "s3:GetBucketVersioning", "s3:GetBucketWebsite", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration", "s3:ListBucket", "s3:ListTagsForResource"]
    resources = ["arn:aws:s3:::pawlocal-${each.value.environment}-*"]
  }

  statement {
    sid       = "DescribeExactEnvironmentCloudFrontFunctionForRefresh"
    effect    = "Allow"
    actions   = ["cloudfront:DescribeFunction"]
    resources = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${each.value.environment}-spa-routing"]
  }

  statement {
    sid       = "ReadExactGitHubOIDCProvider"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"]
  }

  dynamic "statement" {
    for_each = contains(["development-plan", "production-plan"], each.key) ? [true] : []
    content {
      sid    = "ReadExactMatchingEnvironmentRolesForRefresh"
      effect = "Allow"
      actions = [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies"
      ]
      resources = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.value.environment}-terraform-apply",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.value.environment}-github-deploy",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.value.environment}-dsql-runtime"
      ]
    }
  }

  dynamic "statement" {
    for_each = contains(["development-plan", "production-plan"], each.key) ? [true] : []
    content {
      sid       = "ReadExactMatchingEnvironmentPoliciesForRefresh"
      effect    = "Allow"
      actions   = ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyTags", "iam:ListPolicyVersions"]
      resources = local.environment_application_policy_arns[each.value.environment]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ManageOnlyMatchingEnvironmentPolicies"
      effect    = "Allow"
      actions   = ["iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicy", "iam:DeletePolicyVersion", "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyTags", "iam:ListPolicyVersions", "iam:SetDefaultPolicyVersion", "iam:TagPolicy", "iam:UntagPolicy"]
      resources = local.environment_application_policy_arns[each.value.environment]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "AttachOnlyMatchingApplicationPolicyToApplyRole"
      effect    = "Allow"
      actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.value.environment}-terraform-apply"]
      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        # environment_permissions.tf defines this list ordering: index 0 is the
        # environment application policy and index 3 is its DSQL setup policy.
        # Production alone adds index 4, the default-off teardown policy.
        values = concat([
          local.environment_application_policy_arns[each.value.environment][0],
          local.environment_application_policy_arns[each.value.environment][3]
          ], each.value.environment == "production" ? [
          local.environment_application_policy_arns[each.value.environment][4]
        ] : [])
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "AttachOnlyMatchingPublishPolicyToPublishRole"
      effect    = "Allow"
      actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.value.environment}-github-deploy"]
      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        values   = [local.environment_application_policy_arns[each.value.environment][1]]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "AttachOnlyMatchingRuntimePolicyToRuntimeRole"
      effect    = "Allow"
      actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.value.environment}-dsql-runtime"]
      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        values   = [local.environment_application_policy_arns[each.value.environment][2]]
      }
    }
  }
}

resource "aws_iam_role_policy" "github_terraform" {
  for_each = local.role_definitions

  name   = "${each.value.role_name}-permissions"
  role   = aws_iam_role.github_terraform[each.key].id
  policy = data.aws_iam_policy_document.role_permissions[each.key].json
}

import {
  for_each = var.import_existing_github_oidc_provider ? {
    existing = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
  } : {}
  to = aws_iam_openid_connect_provider.github[0]
  id = each.value
}
