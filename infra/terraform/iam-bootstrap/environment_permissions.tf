# Scoped, non-destructive service permissions for the Terraform environment
# apply roles. Deletes and replacement permissions are deliberately omitted.
data "aws_iam_policy_document" "environment_service_apply" {
  for_each = local.environments

  statement {
    sid       = "CreateOnlyEnvironmentNamedFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:CreateBucket"]
    resources = ["arn:aws:s3:::pawlocal-${each.key}-*"]
  }

  statement {
    sid       = "TagOnlyEnvironmentNamedFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:PutBucketTagging"]
    resources = ["arn:aws:s3:::pawlocal-${each.key}-*"]
  }

  statement {
    sid    = "ConfigureOnlyTaggedEnvironmentFrontendBucket"
    effect = "Allow"
    actions = [
      "s3:PutBucketOwnershipControls", "s3:PutPublicAccessBlock",
      "s3:PutEncryptionConfiguration", "s3:PutBucketPolicy"
    ]
    resources = ["arn:aws:s3:::pawlocal-${each.key}-*"]
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
    sid       = "CreateTaggedEnvironmentDsqlCluster"
    effect    = "Allow"
    actions   = ["dsql:CreateCluster"]
    resources = ["arn:aws:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*"]
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
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter", "Name", "purpose"]
    }
  }

  statement {
    sid    = "UpdateOnlyTaggedEnvironmentDsqlCluster"
    effect = "Allow"
    actions = [
      "dsql:UpdateCluster", "dsql:PutClusterPolicy", "dsql:TagResource"
    ]
    resources = ["arn:aws:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*"]
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
    sid       = "CreateTaggedLightsailApiResources"
    effect    = "Allow"
    actions   = ["lightsail:CreateContainerService", "lightsail:CreateCertificate"]
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
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid     = "TagOnlyNamedEnvironmentLightsailResources"
    effect  = "Allow"
    actions = ["lightsail:TagResource"]
    resources = [
      "arn:aws:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/${each.value.service_name}",
      "arn:aws:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:Certificate/${each.value.certificate}"
    ]
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
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid    = "UpdateOnlyTaggedLightsailApiService"
    effect = "Allow"
    actions = [
      "lightsail:UpdateContainerService", "lightsail:CreateContainerServiceDeployment"
    ]
    resources = [
      "arn:aws:lightsail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ContainerService/${each.value.service_name}"
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

  statement {
    sid       = "CreateTaggedCloudFrontDistributionAndFunction"
    effect    = "Allow"
    actions   = ["cloudfront:CreateDistribution", "cloudfront:CreateFunction"]
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
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid       = "TagOnlyNamedEnvironmentCloudFrontFunction"
    effect    = "Allow"
    actions   = ["cloudfront:TagResource"]
    resources = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${each.key}-spa-routing"]
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
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid       = "TagAccountCloudFrontDistributionsForMVP"
    effect    = "Allow"
    actions   = ["cloudfront:TagResource"]
    resources = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"]
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
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }

  statement {
    sid       = "UpdateTaggedAccountCloudFrontDistributionsForMVP"
    effect    = "Allow"
    actions   = ["cloudfront:UpdateDistribution"]
    resources = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"]
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
    sid     = "UpdateOnlyNamedEnvironmentCloudFrontFunction"
    effect  = "Allow"
    actions = ["cloudfront:UpdateFunction", "cloudfront:PublishFunction"]
    resources = [
      "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:function/pawlocal-${each.key}-spa-routing"
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

  statement {
    sid       = "CreateTaggedEnvironmentCognitoUserPool"
    effect    = "Allow"
    actions   = ["cognito-idp:CreateUserPool"]
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
    sid    = "UpdateOnlyTaggedEnvironmentCognitoPool"
    effect = "Allow"
    actions = [
      "cognito-idp:UpdateUserPool", "cognito-idp:CreateUserPoolClient",
      "cognito-idp:UpdateUserPoolClient", "cognito-idp:CreateUserPoolDomain",
      "cognito-idp:UpdateUserPoolDomain", "cognito-idp:TagResource"
    ]
    resources = ["arn:aws:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/*"]
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
    sid       = "ChangeOnlyEnvironmentDnsNames"
    effect    = "Allow"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = ["arn:aws:route53:::hostedzone/${var.route53_zone_id}"]
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsActions"
      values   = ["CREATE", "UPSERT"]
    }
    condition {
      test     = "ForAllValues:StringLike"
      variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
      values = [
        "${each.value.api_name}.${var.domain_name}",
        "${each.value.frontend}.${var.domain_name}",
        "_*.${each.value.api_name}.${var.domain_name}"
      ]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsRecordTypes"
      values   = ["A", "AAAA", "CNAME"]
    }
  }
}

resource "aws_iam_role_policy" "environment_service_apply" {
  for_each = local.environments

  name   = "pawlocal-${each.key}-terraform-application-services"
  role   = aws_iam_role.github_terraform["${each.key}-apply"].id
  policy = data.aws_iam_policy_document.environment_service_apply[each.key].json
}
