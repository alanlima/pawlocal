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
    sid       = "ReadOnlyTaggedPublicConfiguration"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = [var.project_name]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = [each.key]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/configuration-access"
      values   = ["github-public"]
    }
  }
}

resource "aws_iam_role_policy" "configuration_reader" {
  for_each = local.environments

  name   = "pawlocal-${each.key}-configuration-read"
  role   = aws_iam_role.configuration_reader[each.key].id
  policy = data.aws_iam_policy_document.configuration_reader[each.key].json

  # Same-state tags precede the switch; application-state ordering is an operator gate.
  depends_on = [aws_ssm_parameter.configuration]
}
