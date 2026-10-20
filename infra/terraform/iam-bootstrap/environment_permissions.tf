locals {
  environment_application_policy_arns = {
    for environment in keys(local.environments) : environment => [
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-application",
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-frontend-publish",
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-runtime"
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
    "route53:Get*", "route53:List*",
    "sts:GetCallerIdentity", "tag:GetResources"
  ]
  environment_apply_boundary_max_bytes = 5500
}

# Bootstrap owns this maximum-permission envelope. Environment roots own the
# three named policies and may attach them only to their matching roles.
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
    actions   = ["iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicy", "iam:DeletePolicyVersion", "iam:SetDefaultPolicyVersion", "iam:TagPolicy", "iam:UntagPolicy"]
    resources = local.environment_application_policy_arns[each.key]
  }

  statement {
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
    effect    = "Allow"
    actions   = ["s3:CreateBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:PutBucketTagging"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${each.key}-*"]
  }

  statement {
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

  dynamic "statement" {
    for_each = (
      each.key == "development"
      ? var.development_distribution_arn == "" && var.development_oac_arn == ""
      : var.production_distribution_arn == "" && var.production_oac_arn == ""
    ) ? [true] : []
    content {
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
  }

  dynamic "statement" {
    for_each = (
      each.key == "development"
      ? var.development_distribution_arn == "" && var.development_oac_arn == ""
      : var.production_distribution_arn == "" && var.production_oac_arn == ""
    ) ? [true] : []
    content {
      effect    = "Allow"
      actions   = ["cloudfront:TagResource"]
      resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"]
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
  }

  dynamic "statement" {
    for_each = (
      each.key == "development"
      ? var.development_distribution_arn == "" && var.development_oac_arn == ""
      : var.production_distribution_arn == "" && var.production_oac_arn == ""
    ) ? [true] : []
    content {
      effect    = "Allow"
      actions   = ["cloudfront:CreateOriginAccessControl"]
      resources = ["*"]
    }
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateFunction", "cloudfront:DeleteFunction", "cloudfront:DescribeFunction", "cloudfront:PublishFunction", "cloudfront:UpdateFunction"]
    resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${each.key}-spa-routing"]
  }

  dynamic "statement" {
    for_each = each.key == "development" && var.development_distribution_arn != "" ? [var.development_distribution_arn] : each.key == "production" && var.production_distribution_arn != "" ? [var.production_distribution_arn] : []
    content {
      effect    = "Allow"
      actions   = ["cloudfront:DeleteDistribution", "cloudfront:UpdateDistribution"]
      resources = [statement.value]
    }
  }

  dynamic "statement" {
    for_each = each.key == "development" && var.development_oac_arn != "" ? [var.development_oac_arn] : each.key == "production" && var.production_oac_arn != "" ? [var.production_oac_arn] : []
    content {
      effect    = "Allow"
      actions   = ["cloudfront:DeleteOriginAccessControl", "cloudfront:UpdateOriginAccessControl"]
      resources = [statement.value]
    }
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
      error_message = "The ${each.key} apply boundary is ${length(data.aws_iam_policy_document.environment_apply_boundary[each.key].minified_json)} bytes; it must stay within the 5500-byte repository budget (AWS maximum: 6144 bytes)."
    }
  }
}
