locals {
  legacy_operations_roles = {
    plan = {
      name    = "pawlocal-legacy-terraform-plan"
      subject = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:infrastructure-plan"
    }
    apply = {
      name    = "pawlocal-legacy-terraform-apply"
      subject = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:infrastructure-apply"
    }
  }
}

# Preserve the existing bootstrap-owned role objects while making both retired
# identities read-only. The combined-state workflows are inert and these roles
# have no state lock/write, IAM mutation, or application-service mutation.
data "aws_iam_policy_document" "legacy_role_trust" {
  for_each = local.legacy_operations_roles

  statement {
    sid     = "ExactRetiredGitHubEnvironment"
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

resource "aws_iam_role" "legacy_terraform" {
  for_each = local.legacy_operations_roles

  name                 = each.value.name
  assume_role_policy   = data.aws_iam_policy_document.legacy_role_trust[each.key].json
  description          = "Retired PawLocal combined-state ${each.key} role; retained read-only during Issue #135."
  max_session_duration = 3600
  tags = {
    purpose = "retired-${each.key}"
  }
}

data "aws_iam_policy_document" "legacy_role_permissions" {
  for_each = local.legacy_operations_roles

  statement {
    sid       = "ReadOnlyFormerStateObject"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate"]
  }

  statement {
    sid       = "ListOnlyFormerStateKey"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}"]
    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = ["pawlocal/terraform.tfstate"]
    }
  }

  statement {
    sid       = "ReadStateBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}"]
  }

  statement {
    sid       = "IdentifySessionOnly"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "legacy_terraform" {
  for_each = local.legacy_operations_roles

  name   = "${each.value.name}-permissions"
  role   = aws_iam_role.legacy_terraform[each.key].id
  policy = data.aws_iam_policy_document.legacy_role_permissions[each.key].json
}
