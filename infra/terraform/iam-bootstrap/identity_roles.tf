locals {
  identity_state_key = "pawlocal/identity/terraform.tfstate"
  identity_role_specs = {
    identity-plan = {
      role_name = "pawlocal-identity-terraform-plan"
      purpose   = "plan"
      subject   = local.github_main_ref_subject
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
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-dsql-runtime"
  ]
  identity_app_role_arns = {
    development_frontend = aws_iam_role.identity_app["development_frontend"].arn
    production_frontend  = aws_iam_role.identity_app["production_frontend"].arn
    development_runtime  = var.development_lightsail_principal_arn == "" ? null : aws_iam_role.development_runtime[0].arn
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
}

data "aws_iam_policy_document" "identity_app_role_trust" {
  for_each = local.identity_app_role_specs

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
  for_each = local.identity_app_role_specs

  name                 = each.value.name
  description          = each.value.description
  assume_role_policy   = data.aws_iam_policy_document.identity_app_role_trust[each.key].json
  permissions_boundary = aws_iam_policy.identity_app_role_boundary.arn
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = each.key == "development_frontend" ? "development" : "production"
    managedby   = "terraform"
    purpose     = "frontend-publish"
  }
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
  permissions_boundary = aws_iam_policy.identity_app_role_boundary.arn
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = "development"
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

  statement {
    sid       = "WriteOnlyIdentityStateObject"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket_name}/${local.identity_state_key}"]
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
      resources = ["${aws_s3_bucket.plan_transfer.arn}/plans/identity/*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "ReadIdentityPlan"
      effect    = "Allow"
      actions   = ["s3:GetObject"]
      resources = ["${aws_s3_bucket.plan_transfer.arn}/plans/identity/*"]
    }
  }

  statement {
    sid       = "ReadOnlyExactIdentityRolesPoliciesAndOIDC"
    effect    = "Allow"
    actions   = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:GetOpenIDConnectProvider"]
    resources = concat(local.identity_role_resource_arns, [local.oidc_arn])
  }

  statement {
    sid     = "ReadOnlyBootstrapManagedIdentityPolicies"
    effect  = "Allow"
    actions = ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions"]
    resources = [
      aws_iam_policy.identity_development_frontend.arn,
      aws_iam_policy.identity_production_frontend.arn,
      aws_iam_policy.identity_development_runtime.arn,
      aws_iam_policy.identity_app_role_boundary.arn
    ]
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "AttachDevelopmentPublisherPolicyOnlyToDevelopmentRole"
      effect    = "Allow"
      actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      resources = [local.identity_role_resource_arns[0]]
      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        values   = [aws_iam_policy.identity_development_frontend.arn]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "AttachProductionPublisherPolicyOnlyToProductionRole"
      effect    = "Allow"
      actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      resources = [local.identity_role_resource_arns[1]]
      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        values   = [aws_iam_policy.identity_production_frontend.arn]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "AttachDevelopmentRuntimePolicyOnlyToRuntimeRole"
      effect    = "Allow"
      actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      resources = [local.identity_role_resource_arns[2]]
      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        values   = [aws_iam_policy.identity_development_runtime.arn]
      }
    }
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

output "identity_managed_policy_arns" {
  description = "Bootstrap-owned fixed app policies and required IAM permissions boundary for identity-stage roles."
  value = {
    development_frontend = aws_iam_policy.identity_development_frontend.arn
    production_frontend  = aws_iam_policy.identity_production_frontend.arn
    development_runtime  = aws_iam_policy.identity_development_runtime.arn
    boundary             = aws_iam_policy.identity_app_role_boundary.arn
  }
}

output "identity_app_role_arns" {
  description = "Bootstrap-owned application role ARNs; identity state may attach only the fixed policies to these roles."
  value       = local.identity_app_role_arns
}
