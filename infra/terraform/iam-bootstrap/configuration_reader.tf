locals {
  # Keep this exact allowlist in parity with the active configuration inventory
  # and mapping. Readers never discover keys or read an environment subtree.
  configuration_parameter_suffixes = toset([
    "iam/terraform-plan-role-arn",
    "iam/terraform-apply-role-arn",
    "aws/account-id",
    "terraform/plan-bucket",
    "iam/frontend-publish-role-arn",
    "iam/runtime-role-arn",
    "frontend/base-url",
    "api/health-url",
    "frontend/bucket",
    "frontend/cloudfront-distribution-id",
    "frontend/cloudfront-distribution-arn",
    "frontend/cloudfront-oac-arn",
    "auth/client-id",
    "api/base-url",
    "auth/domain",
    "auth/redirect-uri",
    "auth/logout-uri",
    "auth/scopes"
  ])
}

data "aws_iam_policy_document" "configuration_reader_trust" {
  for_each = local.environments

  statement {
    sid     = "ExactProtectedConfigurationEnvironment"
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
      values   = ["repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:${each.key}-apply"]
    }
  }
}

resource "aws_iam_role" "configuration_reader" {
  for_each = local.environments

  name                 = "pawlocal-${each.key}-configuration-reader"
  description          = "Read only approved PawLocal ${each.key} configuration parameters."
  assume_role_policy   = data.aws_iam_policy_document.configuration_reader_trust[each.key].json
  max_session_duration = 3600
  tags = {
    environment = each.key
    purpose     = "configuration-read"
  }
}

data "aws_iam_policy_document" "configuration_reader" {
  for_each = local.environments

  statement {
    sid     = "ReadOnlyExplicitEnvironmentConfiguration"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      for suffix in sort(tolist(local.configuration_parameter_suffixes)) :
      "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/pawlocal/${each.key}/config/${suffix}"
    ]
  }
}

resource "aws_iam_role_policy" "configuration_reader" {
  for_each = local.environments

  name   = "pawlocal-${each.key}-configuration-read"
  role   = aws_iam_role.configuration_reader[each.key].id
  policy = data.aws_iam_policy_document.configuration_reader[each.key].json
}
