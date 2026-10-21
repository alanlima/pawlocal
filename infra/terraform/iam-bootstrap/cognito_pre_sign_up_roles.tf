locals {
  cognito_pre_sign_up_roles = {
    for environment in keys(local.environments) : environment => {
      role_name      = "pawlocal-${environment}-cognito-pre-signup"
      log_group_name = "/aws/lambda/pawlocal-${environment}-cognito-pre-signup"
    }
  }
}

data "aws_iam_policy_document" "cognito_pre_sign_up_trust" {
  for_each = local.cognito_pre_sign_up_roles

  statement {
    sid     = "AllowLambdaServiceOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cognito_pre_sign_up" {
  for_each = local.cognito_pre_sign_up_roles

  name               = each.value.role_name
  description        = "PawLocal ${each.key} Cognito pre sign-up Lambda execution role."
  assume_role_policy = data.aws_iam_policy_document.cognito_pre_sign_up_trust[each.key].json
  tags = {
    project     = "pawlocal"
    environment = each.key
    managedby   = "terraform"
    purpose     = "cognito-pre-signup"
  }
}

data "aws_iam_policy_document" "cognito_pre_sign_up_logs" {
  for_each = local.cognito_pre_sign_up_roles

  statement {
    sid       = "WriteOnlyMatchingFunctionLogStreams"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${each.value.log_group_name}:*"]
  }
}

resource "aws_iam_role_policy" "cognito_pre_sign_up_logs" {
  for_each = local.cognito_pre_sign_up_roles

  name   = "${each.value.role_name}-logs"
  role   = aws_iam_role.cognito_pre_sign_up[each.key].id
  policy = data.aws_iam_policy_document.cognito_pre_sign_up_logs[each.key].json
}

output "cognito_pre_sign_up_role_arns" {
  description = "Bootstrap-owned Cognito pre sign-up Lambda execution-role ARNs keyed by environment."
  value       = { for environment, role in aws_iam_role.cognito_pre_sign_up : environment => role.arn }
}
