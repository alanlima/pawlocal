locals {
  legacy_operations_roles = {
    plan = {
      name        = "pawlocal-legacy-terraform-plan"
      environment = "infrastructure-plan"
      purpose     = "plan"
    }
    apply = {
      name        = "pawlocal-legacy-terraform-apply"
      environment = "infrastructure-apply"
      purpose     = "apply"
    }
  }

  legacy_main_subject  = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:infrastructure-plan"
  legacy_apply_subject = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:infrastructure-apply"

  # Shared by plan and apply roles because both refresh the complete combined
  # root. Includes the AWS provider's aws_s3_bucket read calls and full-stack
  # data/resource refresh calls; keep this read-only list separate from apply
  # mutations below.
  legacy_read_actions = distinct(concat(
    local.readonly_discovery_actions,
    local.regional_read_actions,
    [
      "acm:ListTagsForCertificate",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:ListOriginAccessControls",
      "cloudfront:DescribeFunction",
      "cognito-idp:DescribeUserPool",
      "cognito-idp:DescribeUserPoolClient",
      "cognito-idp:DescribeUserPoolDomain",
      "dsql:ListClusters",
      "iam:GetOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviders",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "lightsail:GetContainerServices",
      "lightsail:GetCertificates",
      "route53:GetHostedZone",
      "route53:ListHostedZones",
      "route53:ListTagsForResource",
      "route53:ListResourceRecordSets",
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetBucketLocation",
      "s3:GetBucketLogging",
      "s3:GetBucketObjectLockConfiguration",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketRequestPayment",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetBucketWebsite",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:ListBucket",
      "s3:ListBucketVersions"
    ]
  ))

  # These actions match the resources in the legacy combined root. CloudFront
  # distribution IDs are generated and its distributions currently have no
  # ownership tags, so update/delete permissions must cover every distribution
  # in this AWS account. Resource creation APIs also require Resource="*".
  legacy_cloudfront_actions = [
    "cloudfront:CreateDistribution", "cloudfront:DeleteDistribution",
    "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig",
    "cloudfront:ListDistributions", "cloudfront:TagResource",
    "cloudfront:UntagResource", "cloudfront:UpdateDistribution",
    "cloudfront:CreateFunction", "cloudfront:DeleteFunction",
    "cloudfront:DescribeFunction", "cloudfront:PublishFunction",
    "cloudfront:UpdateFunction", "cloudfront:CreateOriginAccessControl",
    "cloudfront:DeleteOriginAccessControl", "cloudfront:GetOriginAccessControl",
    "cloudfront:GetOriginAccessControlConfig", "cloudfront:UpdateOriginAccessControl",
    "cloudfront:ListOriginAccessControls", "cloudfront:ListTagsForResource"
  ]
}

data "aws_iam_policy_document" "legacy_role_trust" {
  for_each = local.legacy_operations_roles

  statement {
    sid     = "ExactProtectedGitHubEnvironment"
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
      values   = [each.value.purpose == "plan" ? local.legacy_main_subject : local.legacy_apply_subject]
    }
  }
}

resource "aws_iam_role" "legacy_terraform" {
  for_each = local.legacy_operations_roles

  name                 = each.value.name
  assume_role_policy   = data.aws_iam_policy_document.legacy_role_trust[each.key].json
  description          = "PawLocal ${each.value.purpose} role for the legacy combined Terraform state."
  max_session_duration = 3600
  tags = {
    project   = "pawlocal"
    managedby = "terraform"
    purpose   = "legacy-terraform-${each.value.purpose}"
  }
}

data "aws_iam_policy_document" "legacy_role_permissions" {
  for_each = local.legacy_operations_roles

  statement {
    sid       = "ReadLegacyCombinedState"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate"]
  }

  statement {
    sid       = "LockLegacyCombinedState"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate.tflock"]
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "WriteLegacyCombinedState"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate"]
    }
  }
  statement {
    sid       = "ListLegacyStatePrefix"
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
    sid       = "ReadStateBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
  }

  dynamic "statement" {
    for_each = each.value.purpose == "plan" ? [true] : []
    content {
      sid       = "UploadExactRunPlanToPrivateTransferBucket"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = ["${local.plan_transfer_bucket_arn}/plans/legacy/*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ReadExactRunPlanFromPrivateTransferBucket"
      effect    = "Allow"
      actions   = ["s3:GetObject"]
      resources = ["${local.plan_transfer_bucket_arn}/plans/legacy/*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "plan" ? [true] : []
    content {
      sid       = "ReadOnlyLegacyStackResources"
      effect    = "Allow"
      actions   = local.legacy_read_actions
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ReadLegacyStackResourcesForApplyAndDestroy"
      effect    = "Allow"
      actions   = local.legacy_read_actions
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "ManageLegacyS3BucketsAndObjects"
      effect = "Allow"
      actions = [
        "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketTagging",
        "s3:DeleteBucketTagging", "s3:PutBucketOwnershipControls",
        "s3:DeleteBucketOwnershipControls", "s3:PutPublicAccessBlock",
        "s3:DeletePublicAccessBlock", "s3:PutEncryptionConfiguration",
        "s3:DeleteEncryptionConfiguration", "s3:PutBucketPolicy",
        "s3:DeleteBucketPolicy", "s3:PutBucketVersioning",
        "s3:PutLifecycleConfiguration", "s3:DeleteLifecycleConfiguration",
        "s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutObject"
      ]
      resources = [
        "arn:aws:s3:::pawlocal-*", "arn:aws:s3:::pawlocal-*/*"
      ]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "ManageLegacyCloudFrontResources"
      effect = "Allow"
      actions = [for action in local.legacy_cloudfront_actions : action if !contains([
        "cloudfront:CreateDistribution", "cloudfront:CreateFunction",
        "cloudfront:CreateOriginAccessControl", "cloudfront:ListDistributions",
        "cloudfront:ListFunctions", "cloudfront:ListOriginAccessControls"
      ], action)]
      resources = [
        "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*",
        "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-*",
        "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:origin-access-control/*"
      ]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "CreateLegacyCloudFrontResources"
      effect = "Allow"
      actions = [
        "cloudfront:CreateDistribution", "cloudfront:CreateFunction",
        "cloudfront:CreateOriginAccessControl"
      ]
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "ManageLegacyCognitoPools"
      effect = "Allow"
      actions = [
        "cognito-idp:CreateUserPool"
      ]
      resources = ["*"]
      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/project"
        values   = ["pawlocal"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "UpdateOrDeleteTaggedLegacyCognitoPools"
      effect = "Allow"
      actions = [
        "cognito-idp:DeleteUserPool", "cognito-idp:UpdateUserPool",
        "cognito-idp:DeleteUserPoolClient", "cognito-idp:UpdateUserPoolClient",
        "cognito-idp:DeleteUserPoolDomain", "cognito-idp:UpdateUserPoolDomain",
        "cognito-idp:TagResource", "cognito-idp:UntagResource",
        "cognito-idp:CreateUserPoolClient", "cognito-idp:CreateUserPoolDomain"
      ]
      resources = ["arn:aws:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/*"]
      condition {
        test     = "StringEquals"
        variable = "aws:ResourceTag/project"
        values   = ["pawlocal"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "ManageLegacyDsqlClusters"
      effect = "Allow"
      actions = [
        "dsql:CreateCluster"
      ]
      resources = ["arn:aws:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*"]
      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/environment"
        values   = ["development", "production"]
      }
      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/purpose"
        values   = ["pawlocal-app-database"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "UpdateOrDeletePawLocalDsqlClusters"
      effect = "Allow"
      actions = [
        "dsql:DeleteCluster", "dsql:UpdateCluster", "dsql:PutClusterPolicy",
        "dsql:DeleteClusterPolicy", "dsql:TagResource", "dsql:UntagResource"
      ]
      resources = ["arn:aws:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*"]
      condition {
        test     = "StringEquals"
        variable = "aws:ResourceTag/environment"
        values   = ["development", "production"]
      }
      condition {
        test     = "StringEquals"
        variable = "aws:ResourceTag/purpose"
        values   = ["pawlocal-app-database"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "ManageLegacyLightsailApiResources"
      effect = "Allow"
      actions = [
        "lightsail:CreateContainerService", "lightsail:CreateCertificate"
      ]
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "ManageNamedLegacyLightsailApiResources"
      effect = "Allow"
      actions = [
        "lightsail:DeleteContainerService", "lightsail:UpdateContainerService",
        "lightsail:CreateContainerServiceDeployment", "lightsail:DeleteCertificate",
        "lightsail:TagResource", "lightsail:UntagResource"
      ]
      resources = [
        "arn:aws:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/pawlocal-*",
        "arn:aws:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:Certificate/pawlocal-*"
      ]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid    = "ManageLegacyPawLocalIamRoles"
      effect = "Allow"
      actions = [
        "iam:CreateRole", "iam:DeleteRole", "iam:UpdateAssumeRolePolicy",
        "iam:UpdateRoleDescription", "iam:TagRole", "iam:UntagRole",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy"
      ]
      resources = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-frontend-github-deploy",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-github-deploy",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-github-deploy",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-terraform-deploy",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-terraform-deploy",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-dsql-runtime",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-dsql-runtime"
      ]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ChangeOnlyPawLocalDnsRecords"
      effect    = "Allow"
      actions   = ["route53:ChangeResourceRecordSets"]
      resources = ["arn:aws:route53:::hostedzone/${var.route53_zone_id}"]
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "route53:ChangeResourceRecordSetsActions"
        values   = ["CREATE", "UPSERT", "DELETE"]
      }
      condition {
        test     = "ForAllValues:StringLike"
        variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
        values   = ["pawlocal.${var.domain_name}", "pawlocal-dev.${var.domain_name}", "api.${var.domain_name}", "api-dev.${var.domain_name}", "_*.api.${var.domain_name}", "_*.api-dev.${var.domain_name}"]
      }
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "route53:ChangeResourceRecordSetsRecordTypes"
        values   = ["A", "AAAA", "CNAME"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ReadExactExternalCertificate"
      effect    = "Allow"
      actions   = ["acm:DescribeCertificate", "acm:ListCertificates", "acm:ListTagsForCertificate"]
      resources = ["*"]
    }
  }
}

resource "aws_iam_role_policy" "legacy_terraform" {
  for_each = local.legacy_operations_roles

  name   = "${each.value.name}-permissions"
  role   = aws_iam_role.legacy_terraform[each.key].id
  policy = data.aws_iam_policy_document.legacy_role_permissions[each.key].json
}
