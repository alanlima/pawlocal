data "aws_iam_policy_document" "application" {
  statement {
    sid       = "CreateOnlyTaggedMatchingFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:CreateBucket", "s3:TagResource"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/environment"
      values   = [var.environment]
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
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid       = "TagOnlyMatchingFrontendBucketName"
    effect    = "Allow"
    actions   = ["s3:PutBucketTagging"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*"]
  }

  statement {
    sid    = "ReadOnlyMatchingFrontendBucketBeforeTagHandoff"
    effect = "Allow"
    actions = [
      "s3:GetAccelerateConfiguration", "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketLocation",
      "s3:GetBucketLogging", "s3:GetBucketObjectLockConfiguration", "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketRequestPayment", "s3:GetBucketTagging",
      "s3:GetBucketVersioning", "s3:GetBucketWebsite", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration", "s3:ListBucket", "s3:ListTagsForResource"
    ]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*"]
  }

  statement {
    sid    = "ManageOnlyMatchingFrontendBucketName"
    effect = "Allow"
    actions = [
      "s3:DeleteBucket", "s3:PutBucketOwnershipControls", "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock", "s3:PutEncryptionConfiguration"
    ]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*"]
  }

  statement {
    sid    = "CreateTaggedEnvironmentResources"
    effect = "Allow"
    actions = concat(
      ["cloudfront:CreateFunction", "cognito-idp:CreateUserPool", "lightsail:CreateCertificate", "lightsail:CreateContainerService"],
      var.cloudfront_distribution_arn == "" && var.cloudfront_oac_arn == "" ? ["cloudfront:CreateDistribution"] : []
    )
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/environment"
      values   = [var.environment]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid     = "TagOnlyNewEnvironmentResources"
    effect  = "Allow"
    actions = ["cloudfront:TagResource", "cognito-idp:TagResource", "lightsail:TagResource"]
    resources = concat([
      "arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${var.environment}-spa-routing",
      "arn:${data.aws_partition.current.partition}:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/*",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:Certificate/*",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/pawlocal-${var.environment}-api"
      ],
      var.cloudfront_distribution_arn == "" && var.cloudfront_oac_arn == "" ? ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"] : []
    )
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = [var.environment]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["pawlocal"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/environment"
      values   = [var.environment]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid       = "CreateAndTagOnlyNewEnvironmentDSQLCluster"
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
      values   = [var.environment]
    }
    dynamic "condition" {
      for_each = local.dsql_tags
      content {
        test     = "StringEquals"
        variable = "aws:RequestTag/${condition.key}"
        values   = [condition.value]
      }
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = keys(local.dsql_tags)
    }
  }

  statement {
    sid    = "ManageOnlyTaggedEnvironmentResources"
    effect = "Allow"
    actions = [
      "dsql:DeleteCluster", "dsql:PutClusterPolicy", "dsql:UpdateCluster",
      "cognito-idp:CreateUserPoolClient", "cognito-idp:CreateUserPoolDomain", "cognito-idp:DeleteUserPool",
      "cognito-idp:DeleteUserPoolClient", "cognito-idp:DeleteUserPoolDomain", "cognito-idp:UpdateUserPool",
      "cognito-idp:UpdateUserPoolClient", "cognito-idp:UpdateUserPoolDomain"
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
      values   = [var.environment]
    }
  }

  statement {
    sid    = "ManageOnlyTaggedMatchingLightsailResources"
    effect = "Allow"
    actions = [
      "lightsail:CreateContainerServiceDeployment", "lightsail:DeleteCertificate",
      "lightsail:DeleteContainerService", "lightsail:UpdateContainerService"
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
      values   = [var.environment]
    }
  }

  dynamic "statement" {
    for_each = var.cloudfront_distribution_arn == "" && var.cloudfront_oac_arn == "" ? [true] : []
    content {
      sid       = "CreateEnvironmentCloudFrontOAC"
      effect    = "Allow"
      actions   = ["cloudfront:CreateOriginAccessControl"]
      resources = ["*"]
    }
  }

  statement {
    sid       = "ManageExactEnvironmentCloudFrontFunction"
    effect    = "Allow"
    actions   = ["cloudfront:DeleteFunction", "cloudfront:DescribeFunction", "cloudfront:PublishFunction", "cloudfront:UpdateFunction"]
    resources = ["arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${var.environment}-spa-routing"]
  }

  dynamic "statement" {
    for_each = var.cloudfront_distribution_arn == "" ? [] : [var.cloudfront_distribution_arn]
    content {
      sid       = "ManageExactHandoffDistribution"
      effect    = "Allow"
      actions   = ["cloudfront:DeleteDistribution", "cloudfront:UpdateDistribution"]
      resources = [statement.value]
    }
  }

  dynamic "statement" {
    for_each = var.cloudfront_oac_arn == "" ? [] : [var.cloudfront_oac_arn]
    content {
      sid       = "ManageExactHandoffOAC"
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
      values   = [local.frontend_hostname, local.api_hostname, "_*.${local.api_hostname}"]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsRecordTypes"
      values   = ["A", "AAAA", "CNAME"]
    }
  }
}

data "aws_iam_policy_document" "frontend_publish" {
  statement {
    sid       = "ListOnlyEnvironmentFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.frontend.arn]
  }
  statement {
    sid       = "PublishOnlyEnvironmentFrontendObjects"
    effect    = "Allow"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]
  }
  statement {
    sid       = "InvalidateOnlyEnvironmentDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.frontend.arn]
  }
}

data "aws_iam_policy_document" "runtime" {
  count = var.runtime_role_arn == "" ? 0 : 1

  statement {
    sid       = "ConnectOnlyToEnvironmentDSQL"
    effect    = "Allow"
    actions   = ["dsql:DbConnect"]
    resources = [aws_dsql_cluster.application.arn]
  }
}
