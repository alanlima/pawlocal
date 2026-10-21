locals {
  identity_state_key = "pawlocal/identity/terraform.tfstate"
  identity_role_specs = {
    identity-plan = {
      role_name = "pawlocal-identity-terraform-plan"
      purpose   = "plan"
      subject   = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:identity-plan"
    }
    identity-apply = {
      role_name = "pawlocal-identity-terraform-apply"
      purpose   = "apply"
      subject   = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:identity-apply"
    }
  }
  identity_role_resource_arns = [
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-github-deploy",
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-github-deploy",
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-dsql-runtime",
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-dsql-runtime"
  ]
  identity_app_role_arns = {
    development_frontend = try(aws_iam_role.identity_app["development_frontend"].arn, null)
    production_frontend  = try(aws_iam_role.identity_app["production_frontend"].arn, null)
    development_runtime  = var.development_lightsail_principal_arn == "" ? null : aws_iam_role.development_runtime[0].arn
    production_runtime   = var.production_lightsail_principal_arn == "" ? null : aws_iam_role.production_runtime[0].arn
  }
  identity_app_role_specs = {
    development_frontend = {
      name        = "pawlocal-development-github-deploy"
      description = "PawLocal development frontend publisher; trust is bootstrap-owned."
      subject     = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:development"
    }
    production_frontend = {
      name        = "pawlocal-production-github-deploy"
      description = "PawLocal production frontend publisher; trust is bootstrap-owned."
      subject     = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:production"
    }
  }
  managed_identity_app_role_specs = local.identity_app_role_specs
}

data "aws_iam_policy_document" "identity_app_role_trust" {
  for_each = local.managed_identity_app_role_specs

  statement {
    sid     = "ExactGitHubEnvironmentSubject"
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
      values   = [each.value.subject]
    }
  }
}

resource "aws_iam_role" "identity_app" {
  for_each = local.managed_identity_app_role_specs

  name                 = each.value.name
  description          = each.value.description
  assume_role_policy   = data.aws_iam_policy_document.identity_app_role_trust[each.key].json
  permissions_boundary = aws_iam_policy.identity_app_role_boundary[each.key == "development_frontend" ? "development" : "production"].arn
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = each.key == "development_frontend" ? "development" : "production"
    managedby   = "terraform"
    purpose     = "frontend-publish"
  }
}

import {
  for_each = var.import_existing_development_deploy_role ? {
    development_frontend = local.identity_app_role_specs.development_frontend.name
  } : {}
  to = aws_iam_role.identity_app[each.key]
  id = each.value
}

data "aws_iam_policy_document" "development_runtime_trust" {
  count = var.development_lightsail_principal_arn == "" ? 0 : 1

  statement {
    sid     = "AllowExactDevelopmentLightsailPrincipal"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.development_lightsail_principal_arn]
    }
  }

  statement {
    sid     = "AllowExactDevelopmentTerraformApply"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type = "AWS"
      identifiers = [
        "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-terraform-apply"
      ]
    }
  }

  statement {
    sid     = "AllowExactDevelopmentSeedWorkflow"
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
      values   = ["repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:development-seed"]
    }
  }
}

resource "aws_iam_role" "development_runtime" {
  count = var.development_lightsail_principal_arn == "" ? 0 : 1

  name                 = "pawlocal-development-dsql-runtime"
  description          = "PawLocal development API DSQL runtime; trust is bootstrap-owned."
  assume_role_policy   = data.aws_iam_policy_document.development_runtime_trust[0].json
  permissions_boundary = aws_iam_policy.identity_app_role_boundary["development"].arn
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = "development"
    managedby   = "terraform"
    purpose     = "dsql-runtime"
  }
}

data "aws_iam_policy_document" "production_runtime_trust" {
  count = var.production_lightsail_principal_arn == "" ? 0 : 1

  statement {
    sid     = "AllowExactProductionLightsailPrincipal"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.production_lightsail_principal_arn]
    }
  }

  statement {
    sid     = "AllowExactProductionTerraformApply"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type = "AWS"
      identifiers = [
        "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-terraform-apply"
      ]
    }
  }
}

resource "aws_iam_role" "production_runtime" {
  count = var.production_lightsail_principal_arn == "" ? 0 : 1

  name                 = "pawlocal-production-dsql-runtime"
  description          = "PawLocal production API DSQL runtime; trust is bootstrap-owned."
  assume_role_policy   = data.aws_iam_policy_document.production_runtime_trust[0].json
  permissions_boundary = aws_iam_policy.identity_app_role_boundary["production"].arn
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = "production"
    managedby   = "terraform"
    purpose     = "dsql-runtime"
  }
}

data "aws_iam_policy_document" "identity_role_trust" {
  for_each = local.identity_role_specs

  statement {
    sid     = "ExactIdentityWorkflowSubject"
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
      values   = [each.value.subject]
    }
  }
}

resource "aws_iam_role" "identity_terraform" {
  for_each = local.identity_role_specs

  name                 = each.value.role_name
  assume_role_policy   = data.aws_iam_policy_document.identity_role_trust[each.key].json
  description          = "PawLocal Terraform ${each.value.purpose} role for the separate identity state."
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = "shared"
    managedby   = "terraform"
    purpose     = each.value.purpose
  }
}

data "aws_iam_policy_document" "identity_terraform_role_permissions" {
  for_each = local.identity_role_specs

  statement {
    sid     = "ReadIdentityAndEnvironmentStateObjects"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "arn:aws:s3:::${var.terraform_state_bucket_name}/${local.identity_state_key}",
      "arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/development/terraform.tfstate",
      "arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/production/terraform.tfstate",
      "arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/iam-bootstrap/terraform.tfstate"
    ]
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "WriteOnlyIdentityStateObject"
      effect    = "Allow"
      actions   = ["s3:GetObject", "s3:PutObject"]
      resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}/${local.identity_state_key}"]
    }
  }

  statement {
    sid       = "AcquireAndReleaseIdentityStateLock"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}/${local.identity_state_key}.tflock"]
  }

  statement {
    sid       = "ListOnlyIdentityAndEnvironmentStateKeys"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        local.identity_state_key, "${local.identity_state_key}.tflock",
        "pawlocal/development/terraform.tfstate", "pawlocal/production/terraform.tfstate",
        "pawlocal/iam-bootstrap/terraform.tfstate"
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
      sid       = "UploadIdentityPlan"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = ["${local.plan_transfer_bucket_arn}/plans/identity/*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ReadIdentityPlan"
      effect    = "Allow"
      actions   = ["s3:GetObject"]
      resources = ["${local.plan_transfer_bucket_arn}/plans/identity/*"]
    }
  }

  statement {
    sid       = "ReadOnlyExactIdentityRolesPoliciesAndOIDC"
    effect    = "Allow"
    actions   = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:GetOpenIDConnectProvider"]
    resources = concat(local.identity_role_resource_arns, [local.oidc_arn])
  }

  statement {
    sid     = "ReadOnlyBootstrapManagedIdentityBoundaries"
    effect  = "Allow"
    actions = ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions"]
    resources = [
      aws_iam_policy.identity_app_role_boundary["development"].arn,
      aws_iam_policy.identity_app_role_boundary["production"].arn
    ]
  }

}

resource "aws_iam_role_policy" "identity_terraform" {
  for_each = local.identity_role_specs

  name   = "${each.value.role_name}-permissions"
  role   = aws_iam_role.identity_terraform[each.key].id
  policy = data.aws_iam_policy_document.identity_terraform_role_permissions[each.key].json
}

output "identity_terraform_role_arns" {
  description = "Dedicated Terraform plan/apply roles for the separate identity state."
  value       = { for key, role in aws_iam_role.identity_terraform : key => role.arn }
}

output "identity_app_boundary_arns" {
  description = "Bootstrap-owned permissions boundaries for the fixed publisher and runtime identity roles."
  value = {
    development = aws_iam_policy.identity_app_role_boundary["development"].arn
    production  = aws_iam_policy.identity_app_role_boundary["production"].arn
  }
}

output "identity_app_role_arns" {
  description = "Bootstrap-owned publisher and conditional runtime role ARNs. Runtime values remain null until exact Lightsail principals are supplied."
  value       = local.identity_app_role_arns
}
