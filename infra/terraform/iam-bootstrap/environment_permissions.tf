locals {
  environment_application_policy_arns = {
    for environment in keys(local.environments) : environment => [
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-application",
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-frontend-publish",
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-runtime"
    ]
  }
}

# Bootstrap owns this maximum-permission envelope. Environment roots own the
# two named policies and may attach them only to their matching roles.
data "aws_iam_policy_document" "environment_apply_boundary" {
  for_each = local.environments

  statement {
    sid     = "UseOnlyMatchingEnvironmentState"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}/${each.value.state_key}",
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}/${each.value.state_key}.tflock"
    ]
  }

  statement {
    sid       = "UseOnlyMatchingPlanObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${local.plan_transfer_bucket_arn}/plans/${each.key}/*"]
  }

  statement {
    sid     = "ReadStateAndPlanBucketMetadata"
    effect  = "Allow"
    actions = ["s3:GetBucketLocation"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}",
      local.plan_transfer_bucket_arn
    ]
  }

  statement {
    sid       = "ListOnlyMatchingStatePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [each.value.state_key, "${each.value.state_key}.tflock"]
    }
  }

  statement {
    sid       = "ReadProviderState"
    effect    = "Allow"
    actions   = concat(local.readonly_discovery_actions, local.regional_read_actions)
    resources = ["*"]
  }

  statement {
    sid       = "ManageOnlyMatchingEnvironmentPolicies"
    effect    = "Allow"
    actions   = ["iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicy", "iam:DeletePolicyVersion", "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyTags", "iam:ListPolicyVersions", "iam:SetDefaultPolicyVersion", "iam:TagPolicy", "iam:UntagPolicy"]
    resources = local.environment_application_policy_arns[each.key]
  }

  statement {
    sid       = "AttachOnlyMatchingApplicationPolicyToApplyRole"
    effect    = "Allow"
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.key}-terraform-apply"]
    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = [local.environment_application_policy_arns[each.key][0]]
    }
  }

  statement {
    sid       = "AttachOnlyMatchingPublishPolicyToPublishRole"
    effect    = "Allow"
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.key}-github-deploy"]
    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = [local.environment_application_policy_arns[each.key][1]]
    }
  }

  statement {
    sid       = "AttachOnlyMatchingRuntimePolicyToRuntimeRole"
    effect    = "Allow"
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.key}-dsql-runtime"]
    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = [local.environment_application_policy_arns[each.key][2]]
    }
  }

  statement {
    sid       = "CreateOnlyMatchingFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:CreateBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*"]
  }

  statement {
    sid       = "TagOnlyMatchingFrontendBucketName"
    effect    = "Allow"
    actions   = ["s3:PutBucketTagging"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*"]
  }

  statement {
    sid    = "ManageOnlyTaggedMatchingFrontendBucket"
    effect = "Allow"
    actions = [
      "s3:DeleteBucket", "s3:Get*", "s3:ListBucket", "s3:PutBucketOwnershipControls",
      "s3:PutBucketPolicy", "s3:PutEncryptionConfiguration", "s3:PutPublicAccessBlock"
    ]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = [each.key]
    }
  }

  statement {
    sid       = "CreateOnlyTaggedEnvironmentResources"
    effect    = "Allow"
    actions   = ["dsql:CreateCluster", "lightsail:CreateCertificate", "lightsail:CreateContainerService", "cognito-idp:CreateUserPool"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/environment"
      values   = [each.key]
    }
  }

  statement {
    sid    = "ManageOnlyTaggedEnvironmentResources"
    effect = "Allow"
    actions = [
      "dsql:DeleteCluster", "dsql:PutClusterPolicy", "dsql:UpdateCluster",
      "cognito-idp:CreateUserPoolClient", "cognito-idp:CreateUserPoolDomain", "cognito-idp:DeleteUserPool",
      "cognito-idp:DeleteUserPoolClient", "cognito-idp:DeleteUserPoolDomain", "cognito-idp:UpdateUserPool",
      "cognito-idp:UpdateUserPoolClient", "cognito-idp:UpdateUserPoolDomain",
      "lightsail:CreateContainerServiceDeployment", "lightsail:DeleteCertificate", "lightsail:DeleteContainerService", "lightsail:UpdateContainerService"
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = [each.key]
    }
  }

  statement {
    sid     = "SetLightsailAuthorizationTagsOnlyOnce"
    effect  = "Allow"
    actions = ["lightsail:TagResource"]
    resources = [
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/${each.value.service_name}",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:Certificate/pawlocal-${each.key}-api"
    ]
    condition {
      test     = "Null"
      variable = "aws:ResourceTag/project"
      values   = ["true"]
    }
    condition {
      test     = "Null"
      variable = "aws:ResourceTag/environment"
      values   = ["true"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/environment"
      values   = [each.key]
    }
  }

  statement {
    sid       = "CreateEnvironmentCloudFrontResources"
    effect    = "Allow"
    actions   = ["cloudfront:CreateDistribution", "cloudfront:CreateFunction", "cloudfront:CreateOriginAccessControl"]
    resources = ["*"]
  }

  statement {
    sid       = "ManageExactEnvironmentCloudFrontFunction"
    effect    = "Allow"
    actions   = ["cloudfront:DeleteFunction", "cloudfront:DescribeFunction", "cloudfront:PublishFunction", "cloudfront:UpdateFunction"]
    resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${each.key}-spa-routing"]
  }

  dynamic "statement" {
    for_each = each.key == "development" && var.development_distribution_arn != "" ? [var.development_distribution_arn] : each.key == "production" && var.production_distribution_arn != "" ? [var.production_distribution_arn] : []
    content {
      sid       = "ManageOnlyExactHandoffDistribution"
      effect    = "Allow"
      actions   = ["cloudfront:DeleteDistribution", "cloudfront:UpdateDistribution"]
      resources = [statement.value]
    }
  }

  dynamic "statement" {
    for_each = each.key == "development" && var.development_oac_arn != "" ? [var.development_oac_arn] : each.key == "production" && var.production_oac_arn != "" ? [var.production_oac_arn] : []
    content {
      sid       = "ManageOnlyExactHandoffOAC"
      effect    = "Allow"
      actions   = ["cloudfront:DeleteOriginAccessControl", "cloudfront:UpdateOriginAccessControl"]
      resources = [statement.value]
    }
  }

  statement {
    sid       = "ChangeOnlyEnvironmentDNSNames"
    effect    = "Allow"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = ["arn:${data.aws_partition.current.partition}:route53:::hostedzone/${var.route53_zone_id}"]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
      values   = ["${each.value.api_name}.${var.domain_name}", "${each.value.frontend}.${var.domain_name}", "_*.${each.value.api_name}.${var.domain_name}"]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsRecordTypes"
      values   = ["A", "AAAA", "CNAME"]
    }
  }
}

resource "aws_iam_policy" "environment_apply_boundary" {
  for_each = local.environments

  name        = "pawlocal-${each.key}-terraform-apply-boundary"
  description = "Maximum permissions for the PawLocal ${each.key} Terraform apply role."
  policy      = data.aws_iam_policy_document.environment_apply_boundary[each.key].json
  tags = {
    project     = "pawlocal"
    environment = each.key
    managedby   = "terraform"
    purpose     = "permissions-boundary"
  }
}
