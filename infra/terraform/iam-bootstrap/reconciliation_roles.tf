locals {
  reconciliation_role_specs = {
    for environment, config in local.environments : environment => {
      role_name             = "pawlocal-${environment}-output-reconciliation"
      subject_environment   = "${environment}-reconcile"
      environment_state_key = config.state_key
    }
  }
  bootstrap_state_key = "pawlocal/iam-bootstrap/terraform.tfstate"
}

data "aws_iam_policy_document" "reconciliation_role_trust" {
  for_each = local.reconciliation_role_specs

  statement {
    sid     = "ExactReconciliationEnvironmentSubject"
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
      values   = ["repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:${each.value.subject_environment}"]
    }
  }
}

resource "aws_iam_role" "output_reconciliation" {
  for_each = local.reconciliation_role_specs

  name               = each.value.role_name
  description        = "Read-only state-output identity for PawLocal ${each.key} reconciliation."
  assume_role_policy = data.aws_iam_policy_document.reconciliation_role_trust[each.key].json
  tags = {
    project     = "pawlocal"
    environment = each.key
    managedby   = "terraform"
    purpose     = "output-reconciliation"
  }
}

data "aws_iam_policy_document" "output_reconciliation" {
  for_each = local.reconciliation_role_specs

  statement {
    sid     = "ReadOnlyExactBootstrapAndEnvironmentStates"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}/${local.bootstrap_state_key}",
      "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}/${each.value.environment_state_key}"
    ]
  }

  statement {
    sid       = "ReadOnlyStateBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}"]
  }
}

resource "aws_iam_role_policy" "output_reconciliation" {
  for_each = local.reconciliation_role_specs

  name   = "${each.value.role_name}-read-state-outputs"
  role   = aws_iam_role.output_reconciliation[each.key].id
  policy = data.aws_iam_policy_document.output_reconciliation[each.key].json
}

output "reconciliation_role_arns" {
  description = "Read-only state-output role ARN for each protected reconciliation environment."
  value       = { for key, role in aws_iam_role.output_reconciliation : key => role.arn }
}
