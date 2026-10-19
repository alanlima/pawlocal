data "aws_caller_identity" "current" {}

data "terraform_remote_state" "app" {
  backend = "s3"
  config = {
    bucket  = var.terraform_state_bucket_name
    key     = "pawlocal/app-infra.tfstate"
    region  = var.aws_region
    encrypt = true
  }
}

locals {
  common_tags = {
    costcenter  = "personal"
    environment = "production"
    managedby   = "terraform"
    project     = "pawlocal"
    component   = "frontend"
    workload    = "static-site"
  }
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]
  environments = ["development", "production"]
  targets      = data.terraform_remote_state.app.outputs.shared_iam_targets
  frontend_role_names = {
    development = "pawlocal-development-github-deploy"
    production  = "pawlocal-frontend-github-deploy"
  }
  frontend_role_trust_subjects = {
    development = ["repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:development"]
    production = [
      "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:ref:refs/heads/main",
      "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:production"
    ]
  }
  all_bucket_arns = distinct(compact(flatten([
    [for target in values(local.targets) : target.frontend_bucket_arn],
    [for target in values(local.targets) : target.audit_bucket_arn],
  ])))
  frontend_bucket_arns   = distinct(compact([for target in values(local.targets) : target.frontend_bucket_arn]))
  spa_function_arns      = compact([for target in values(local.targets) : target.frontend_function_arn])
  cognito_user_pool_arns = compact([for target in values(local.targets) : target.cognito_user_pool_arn])
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = 1
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "frontend_trust_development" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.frontend_role_trust_subjects.development
    }
  }
}

data "aws_iam_policy_document" "frontend_trust_production" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.frontend_role_trust_subjects.production
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  provider           = aws.frontend
  name               = local.frontend_role_names.production
  assume_role_policy = data.aws_iam_policy_document.frontend_trust_production.json
  description        = "Allows PawLocal main-branch and production-environment workflows to publish production frontend files and invalidate the CDN."
}

resource "aws_iam_role" "github_deploy_development" {
  provider           = aws.fullstack
  name               = local.frontend_role_names.development
  assume_role_policy = data.aws_iam_policy_document.frontend_trust_development.json
  description        = "Allows the PawLocal development environment to publish frontend artifacts and invalidate its CDN."
}

data "aws_iam_policy_document" "frontend_publish_development" {
  statement {
    sid       = "ListFrontendBucket"
    actions   = ["s3:ListBucket"]
    resources = [local.targets.development.frontend_bucket_arn]
  }
  statement {
    sid       = "PublishFrontendObjects"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = ["${local.targets.development.frontend_bucket_arn}/*"]
  }
  statement {
    sid       = "InvalidateFrontendDistribution"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [local.targets.development.frontend_distribution_arn]
  }
}

data "aws_iam_policy_document" "frontend_publish_production" {
  statement {
    sid       = "ListFrontendBucket"
    actions   = ["s3:ListBucket"]
    resources = [local.targets.production.frontend_bucket_arn]
  }
  statement {
    sid       = "PublishFrontendObjects"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = ["${local.targets.production.frontend_bucket_arn}/*"]
  }
  statement {
    sid       = "InvalidateFrontendDistribution"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [local.targets.production.frontend_distribution_arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  provider = aws.frontend
  name     = "pawlocal-frontend-publish"
  role     = aws_iam_role.github_deploy.id
  policy   = data.aws_iam_policy_document.frontend_publish_production.json
}

resource "aws_iam_role_policy" "github_deploy_development" {
  provider = aws.fullstack
  role     = aws_iam_role.github_deploy_development.id
  policy   = data.aws_iam_policy_document.frontend_publish_development.json
}

data "aws_iam_policy_document" "terraform_deploy_trust" {
  for_each = toset(local.environments)
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
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

resource "aws_iam_role" "github_terraform_deploy" {
  provider           = aws.fullstack
  for_each           = toset(local.environments)
  name               = "pawlocal-${each.key}-terraform-deploy"
  assume_role_policy = data.aws_iam_policy_document.terraform_deploy_trust[each.key].json
  description        = "Terraform state-backed release deployment for the PawLocal ${each.key} Lightsail container service."
}

data "aws_iam_policy_document" "github_terraform_deploy" {
  for_each = toset(local.environments)

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
    sid       = "DescribePawLocalSpaFunctionsForTerraformRefresh"
    effect    = "Allow"
    actions   = ["cloudfront:DescribeFunction"]
    resources = local.spa_function_arns
  }

  statement {
    sid       = "ReadPawLocalUserPoolMfaForTerraformRefresh"
    effect    = "Allow"
    actions   = ["cognito-idp:GetUserPoolMfaConfig"]
    resources = local.cognito_user_pool_arns
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
    resources = local.all_bucket_arns
  }

  statement {
    sid       = "ListPawLocalFrontendBucketsForTerraformRefresh"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = local.frontend_bucket_arns
  }

  statement {
    sid       = "ReadPawLocalFrontendBucketAccelerationForTerraformRefresh"
    effect    = "Allow"
    actions   = ["s3:GetAccelerateConfiguration"]
    resources = local.frontend_bucket_arns
  }

  dynamic "statement" {
    for_each = each.key == "development" ? [true] : []

    content {
      sid       = "ReadPawLocalFrontendBucketReplicationForTerraformRefresh"
      effect    = "Allow"
      actions   = ["s3:GetReplicationConfiguration"]
      resources = local.frontend_bucket_arns
    }
  }

  statement {
    sid    = "LockAndUpdateAppTerraformState"
    effect = "Allow"
    actions = [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject"
    ]
    resources = [
      "arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/app-infra.tfstate",
      "arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/app-infra.tfstate.tflock"
    ]
  }

  statement {
    sid       = "ListAppTerraformStatePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["pawlocal/app-infra.tfstate", "pawlocal/app-infra.tfstate.tflock"]
    }
  }

  statement {
    sid       = "ReadTerraformStateBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
  }

  statement {
    sid       = "DeployOnlyThisContainerService"
    effect    = "Allow"
    actions   = ["lightsail:CreateContainerServiceDeployment"]
    resources = [local.targets[each.key].api_container_service_arn]
  }
}

resource "aws_iam_role_policy" "github_terraform_deploy" {
  provider = aws.fullstack
  for_each = toset(local.environments)
  name     = "pawlocal-${each.key}-terraform-container-release"
  role     = aws_iam_role.github_terraform_deploy[each.key].id
  policy   = data.aws_iam_policy_document.github_terraform_deploy[each.key].json
}
