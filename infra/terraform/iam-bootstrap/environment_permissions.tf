locals {
  environment_runtime_cluster_arns = {
    development = var.development_dsql_cluster_arn
    production  = var.production_dsql_cluster_arn
  }
  environment_dsql_tags = {
    for environment in keys(local.environments) : environment => {
      project     = "pawlocal"
      environment = environment
      managedby   = "terraform"
      component   = "fullstack-mvp"
      workload    = "application"
      costcenter  = "personal"
      Name        = "pawlocal-${environment}"
      purpose     = "pawlocal-app-database"
    }
  }
  environment_cloudfront_handoff_arns = {
    development = compact([var.development_distribution_arn, var.development_oac_arn])
    production  = compact([var.production_distribution_arn, var.production_oac_arn])
  }
  environment_application_policy_arns = {
    for environment in keys(local.environments) : environment => [
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-application",
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-frontend-publish",
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${environment}-runtime"
    ]
  }
  environment_active_application_policy_arns = {
    for environment in keys(local.environments) : environment => slice(
      local.environment_application_policy_arns[environment],
      0,
      local.environment_runtime_cluster_arns[environment] == "" ? 2 : 3
    )
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
    "sts:GetCallerIdentity"
  ]
  environment_apply_boundary_max_bytes = 6050
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
    actions   = ["iam:*Policy*"]
    resources = local.environment_active_application_policy_arns[each.key]
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

  dynamic "statement" {
    for_each = local.environment_runtime_cluster_arns[each.key] == "" ? [] : [true]
    content {
      effect    = "Allow"
      actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      resources = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.key}-dsql-runtime"]
      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        values   = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/pawlocal-${each.key}-runtime"]
      }
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
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/managedby"
      values   = ["terraform"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/component"
      values   = ["fullstack-mvp"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/workload"
      values   = ["application"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/costcenter"
      values   = ["personal"]
    }
    condition {
      test     = "ForAllValues:StringLike"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
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
      "s3:PutEncryptionConfiguration", "s3:PutPublicAccessBlock"
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
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/${each.value.service_name}"
    ]
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
    for_each = local.environment_runtime_cluster_arns[each.key] == "" ? [true] : []
    content {
      effect    = "Allow"
      actions   = ["dsql:CreateCluster", "dsql:TagResource"]
      resources = ["arn:${data.aws_partition.current.partition}:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*"]
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
      dynamic "condition" {
        for_each = local.environment_dsql_tags[each.key]
        content {
          test     = "StringEquals"
          variable = "aws:RequestTag/${condition.key}"
          values   = [condition.value]
        }
      }
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "aws:TagKeys"
        values   = keys(local.environment_dsql_tags[each.key])
      }
    }
  }

  statement {
    effect = "Allow"
    actions = concat([
      "dsql:DeleteCluster", "dsql:UpdateCluster",
      "cognito-idp:CreateUserPoolClient", "cognito-idp:CreateUserPoolDomain", "cognito-idp:DeleteUserPool",
      "cognito-idp:DeleteUserPoolClient", "cognito-idp:DeleteUserPoolDomain", "cognito-idp:UpdateUserPool",
      "cognito-idp:UpdateUserPoolClient", "cognito-idp:UpdateUserPoolDomain",
      "lightsail:DeleteCertificate", "lightsail:DeleteContainerService", "lightsail:UpdateContainerService"
      ], local.environment_runtime_cluster_arns[each.key] == "" ? [] : [
      "dsql:PutClusterPolicy", "lightsail:CreateContainerServiceDeployment"
    ])
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
    effect = "Allow"
    actions = concat(
      ["cloudfront:DeleteFunction", "cloudfront:DescribeFunction", "cloudfront:PublishFunction", "cloudfront:UpdateFunction"],
      length(local.environment_cloudfront_handoff_arns[each.key]) == 0 ? ["cloudfront:CreateFunction", "cloudfront:TagResource"] : []
    )
    resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${each.key}-spa-routing"]
  }

  dynamic "statement" {
    for_each = length(local.environment_cloudfront_handoff_arns[each.key]) == 0 ? [] : [true]
    content {
      effect    = "Allow"
      actions   = ["cloudfront:DeleteDistribution", "cloudfront:DeleteOriginAccessControl", "cloudfront:UpdateDistribution", "cloudfront:UpdateOriginAccessControl"]
      resources = local.environment_cloudfront_handoff_arns[each.key]
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
      error_message = "The ${each.key} apply boundary is ${length(data.aws_iam_policy_document.environment_apply_boundary[each.key].minified_json)} bytes; it must stay within the 6050-byte repository budget (AWS maximum: 6144 bytes)."
    }
  }
}
