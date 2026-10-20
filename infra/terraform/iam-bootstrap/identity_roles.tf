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
      sid       = "ManageOnlyNamedRolesWithFixedPermissionsBoundary"
      effect    = "Allow"
      actions   = ["iam:UpdateAssumeRolePolicy"]
      resources = local.identity_role_resource_arns
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "CreateRolesOnlyWithBootstrapBoundary"
      effect    = "Allow"
      actions   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
      resources = local.identity_role_resource_arns
      condition {
        test     = "ArnEquals"
        variable = "iam:PermissionsBoundary"
        values   = [aws_iam_policy.identity_app_role_boundary.arn]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.purpose == "apply" ? [true] : []
    content {
      sid       = "TagOnlyNamedIdentityRoles"
      effect    = "Allow"
      actions   = ["iam:TagRole"]
      resources = local.identity_role_resource_arns
      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/project"
        values   = ["pawlocal"]
      }
    }
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
