data "aws_iam_policy_document" "application" {
  statement {
    sid       = "CreateOnlyMatchingFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:CreateBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*"]
  }

  statement {
    sid       = "TagOnlyMatchingFrontendBucketName"
    effect    = "Allow"
    actions   = ["s3:PutBucketTagging"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*"]
  }

  statement {
    sid    = "ManageOnlyTaggedMatchingFrontendBucket"
    effect = "Allow"
    actions = [
      "s3:DeleteBucket", "s3:PutBucketOwnershipControls", "s3:PutBucketPolicy",
      "s3:PutEncryptionConfiguration", "s3:PutPublicAccessBlock"
    ]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::pawlocal-${var.environment}-*"]
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
    sid       = "CreateTaggedEnvironmentResources"
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
      values   = [var.environment]
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

  statement {
    sid     = "SetImmutableAuthorizationTagsOnlyAtLightsailCreation"
    effect  = "Allow"
    actions = ["lightsail:TagResource"]
    resources = [
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/pawlocal-${var.environment}-api",
      "arn:${data.aws_partition.current.partition}:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:Certificate/pawlocal-${var.environment}-api"
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
      values   = [var.environment]
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
