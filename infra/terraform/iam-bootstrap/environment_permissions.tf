locals {
  environment_policy_arns = {
    for environment in keys(local.environments) : environment => {
      application        = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-application"
      frontend_publish   = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-frontend-publish"
      runtime            = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-runtime"
      dsql_setup         = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-dsql-setup"
      cognito_pre_signup = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-cognito-pre-signup-deployment"
      frontend_teardown  = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-frontend-teardown"
    }
  }
  environment_application_policy_arns = {
    for environment, policies in local.environment_policy_arns : environment => [
      policies.application,
      policies.frontend_publish,
      policies.runtime,
      policies.dsql_setup,
      policies.cognito_pre_signup,
      policies.frontend_teardown
    ]
  }
  environment_apply_attachment_policy_arns = {
    for environment, policies in local.environment_policy_arns : environment => [
      policies.application,
      policies.cognito_pre_signup,
      policies.dsql_setup,
      policies.frontend_teardown
    ]
  }
  # Boundaries cap mutation while the matching identity policy retains the
  # provider's exact read list. Read-only wildcards keep the rendered boundary
  # below IAM's managed-policy size limit without increasing effective writes.
  environment_boundary_read_actions = [
    "cloudfront:Get*", "cloudfront:List*",
    "cognito-idp:Describe*", "cognito-idp:Get*", "cognito-idp:List*",
    "dsql:Get*", "dsql:List*",
    "iam:Get*", "iam:List*",
    "lightsail:Get*",
    "logs:Describe*",
    "route53:Get*", "route53:List*",
    "sts:GetCallerIdentity"
  ]
  environment_apply_boundary_max_bytes = 6143
}

# Bootstrap owns this maximum-permission envelope. Environment roots own the
# named policies and may attach them only to their matching roles.
data "aws_iam_policy_document" "environment_apply_boundary" {
  for_each = local.environments

  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}/${each.value.state_key}",
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}/${each.value.state_key}.tflock"
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${local.plan_transfer_bucket_arn}/plans/${each.key}/*"]
  }

  statement {
    effect  = "Allow"
    actions = ["s3:GetBucketLocation"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}",
      local.plan_transfer_bucket_arn
    ]
  }

  statement {
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
    effect    = "Allow"
    actions   = local.environment_boundary_read_actions
    resources = ["*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["iam:*Policy*"]
    resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${each.key}-*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy", "sts:AssumeRole"]
    resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.key}-*"]
    condition {
      test     = "ArnLikeIfExists"
      variable = "iam:PolicyARN"
      values   = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${each.key}-*"]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:CreateBucket", "s3:TagResource"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*"]
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
    effect = "Allow"
    actions = [
      "s3:GetBucket*", "s3:Get*Configuration", "s3:ListBucket", "s3:ListTagsForResource", "s3:PutBucketTagging"
    ]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:DeleteBucket", "s3:PutBucketOwnershipControls", "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock", "s3:PutEncryptionConfiguration", "s3:DeleteObject"
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*",
      "arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*/*"
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["cognito-idp:CreateUserPool", "lightsail:CreateCertificate", "lightsail:CreateContainerService"]
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
    effect  = "Allow"
    actions = ["cognito-idp:TagResource", "lightsail:TagResource"]
    resources = [
      "arn:${data.aws_partition.current.partition}:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/*",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:Certificate/*",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/*"
    ]
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
    effect    = "Allow"
    actions   = ["dsql:CreateCluster", "dsql:TagResource"]
    resources = ["arn:${data.aws_partition.current.partition}:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*"]
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
    effect = "Allow"
    actions = [
      "dsql:DbConnectAdmin", "dsql:DeleteCluster", "dsql:UpdateCluster",
      "dsql:PutClusterPolicy",
      "lightsail:*ContainerService*", "lightsail:DeleteCertificate"
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:Certificate/*",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/*"
    ]
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

  # These actions use disjoint service-specific resource types. Keeping them in
  # one statement reduces policy bytes without widening any compatible ARN.
  statement {
    effect = "Allow"
    actions = [
      "cloudfront:*OriginAccessControl",
      "cognito-idp:CreateUserPool*", "cognito-idp:DeleteUserPool*", "cognito-idp:UpdateUserPool*",
      "lambda:*Permission", "lambda:CreateFunction", "lambda:DeleteFunction", "lambda:Get*", "lambda:List*",
      "lambda:TagResource", "lambda:UntagResource", "lambda:UpdateFunction*",
      "logs:*LogGroup", "logs:*Resource", "logs:ListTagsForResource", "logs:PutRetentionPolicy"
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:origin-access-control/*",
      "arn:${data.aws_partition.current.partition}:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/*",
      "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:pawlocal-${each.key}-cognito-pre-signup",
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/pawlocal-${each.key}-cognito-pre-signup",
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/pawlocal-${each.key}-cognito-pre-signup:*"
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.key}-cognito-pre-signup"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateDistribution"]
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
    effect    = "Allow"
    actions   = ["cloudfront:TagResource"]
    resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"]
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
    effect    = "Allow"
    actions   = ["cloudfront:*Function", "cloudfront:TagResource"]
    resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${each.key}-spa-routing"]
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:DeleteDistribution", "cloudfront:UpdateDistribution"]
    resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"]
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
    effect    = "Allow"
    actions   = ["cloudfront:CreateOriginAccessControl"]
    resources = ["*"]
  }

  statement {
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

  lifecycle {
    precondition {
      condition     = length(data.aws_iam_policy_document.environment_apply_boundary[each.key].minified_json) <= local.environment_apply_boundary_max_bytes
      error_message = "The ${each.key} apply boundary is ${length(data.aws_iam_policy_document.environment_apply_boundary[each.key].minified_json)} bytes; it must stay within the 6143-byte repository budget (AWS maximum: 6144 bytes)."
    }
  }
}
