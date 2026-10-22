locals {
  cognito_terraform_role_definitions = merge(
    { for environment in keys(local.environments) : "${environment}-plan" => {
      environment = environment
      purpose     = "plan"
      role_name   = "pawlocal-${environment}-cognito-terraform-plan"
    } },
    { for environment in keys(local.environments) : "${environment}-apply" => {
      environment = environment
      purpose     = "apply"
      role_name   = "pawlocal-${environment}-cognito-terraform-apply"
    } }
  )

  cognito_resource_names = {
    for environment in keys(local.environments) : environment => {
      function       = "pawlocal-${environment}-cognito-pre-signup"
      log_group      = "/aws/lambda/pawlocal-${environment}-cognito-pre-signup"
      execution_role = "pawlocal-${environment}-cognito-pre-signup"
    }
  }

  cognito_resource_arns = {
    for environment, names in local.cognito_resource_names : environment => {
      function       = "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${names.function}"
      log_group      = "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${names.log_group}:*"
      log_group_tags = "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${names.log_group}"
      log_stream     = "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${names.log_group}:log-stream:*"
      execution_role = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${names.execution_role}"
    }
  }

  cognito_terraform_role_arns = {
    for key, definition in local.cognito_terraform_role_definitions :
    key => "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${definition.role_name}"
  }

  cognito_application_tags = {
    for environment in keys(local.environments) : environment => {
      project     = "pawlocal"
      environment = environment
      managedby   = "terraform"
      component   = "fullstack-mvp"
      workload    = "application"
      costcenter  = "personal"
    }
  }

  cognito_lambda_read_actions = [
    "lambda:GetFunction",
    "lambda:GetFunctionCodeSigningConfig",
    "lambda:GetPolicy",
    "lambda:ListTags",
    "lambda:ListVersionsByFunction"
  ]
  cognito_lambda_mutation_actions = [
    "lambda:AddPermission",
    "lambda:DeleteFunction",
    "lambda:RemovePermission",
    "lambda:UpdateFunctionCode",
    "lambda:UpdateFunctionConfiguration"
  ]
  cognito_logs_mutation_actions = [
    "logs:DeleteLogGroup",
    "logs:PutRetentionPolicy"
  ]
  iam_managed_policy_max_bytes = 6144
}

data "aws_iam_policy_document" "cognito_terraform_trust" {
  for_each = local.cognito_terraform_role_definitions

  statement {
    sid     = "ExactMatchingEnvironmentTerraformRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-${each.value.environment}-terraform-${each.value.purpose}"]
    }
  }
}

data "aws_iam_policy_document" "cognito_plan_permissions" {
  for_each = local.environments

  statement {
    sid       = "ReadExactPreSignUpLambda"
    effect    = "Allow"
    actions   = local.cognito_lambda_read_actions
    resources = [local.cognito_resource_arns[each.key].function]
  }

  statement {
    sid       = "ReadExactPreSignUpLogGroupTags"
    effect    = "Allow"
    actions   = ["logs:ListTagsForResource"]
    resources = [local.cognito_resource_arns[each.key].log_group_tags]
  }

  statement {
    sid       = "DescribeRegionalLogGroupsForProviderRefresh"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }
}

data "aws_iam_policy_document" "cognito_apply_permissions" {
  for_each = local.environments

  statement {
    sid       = "ReadExactPreSignUpLambda"
    effect    = "Allow"
    actions   = local.cognito_lambda_read_actions
    resources = [local.cognito_resource_arns[each.key].function]
  }

  statement {
    sid       = "CreateExactTaggedPreSignUpLambda"
    effect    = "Allow"
    actions   = ["lambda:CreateFunction", "lambda:TagResource"]
    resources = [local.cognito_resource_arns[each.key].function]

    dynamic "condition" {
      for_each = local.cognito_application_tags[each.key]
      content {
        test     = "StringEquals"
        variable = "aws:RequestTag/${condition.key}"
        values   = [condition.value]
      }
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = keys(local.cognito_application_tags[each.key])
    }
  }

  statement {
    sid       = "ManageExactTaggedPreSignUpLambda"
    effect    = "Allow"
    actions   = local.cognito_lambda_mutation_actions
    resources = [local.cognito_resource_arns[each.key].function]
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
    sid       = "TagExactPreSignUpLambdaWithApprovedValues"
    effect    = "Allow"
    actions   = ["lambda:TagResource"]
    resources = [local.cognito_resource_arns[each.key].function]
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
    dynamic "condition" {
      for_each = local.cognito_application_tags[each.key]
      content {
        test     = "StringEqualsIfExists"
        variable = "aws:RequestTag/${condition.key}"
        values   = [condition.value]
      }
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = keys(local.cognito_application_tags[each.key])
    }
  }

  statement {
    sid       = "UntagOnlyNonRequiredPreSignUpLambdaTags"
    effect    = "Allow"
    actions   = ["lambda:UntagResource"]
    resources = [local.cognito_resource_arns[each.key].function]
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
    condition {
      test     = "ForAllValues:StringNotEquals"
      variable = "aws:TagKeys"
      values   = keys(local.cognito_application_tags[each.key])
    }
  }

  statement {
    sid       = "CreateExactTaggedPreSignUpLogGroup"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup"]
    resources = [local.cognito_resource_arns[each.key].log_group]

    dynamic "condition" {
      for_each = local.cognito_application_tags[each.key]
      content {
        test     = "StringEquals"
        variable = "aws:RequestTag/${condition.key}"
        values   = [condition.value]
      }
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = keys(local.cognito_application_tags[each.key])
    }
  }


  # CloudWatch Logs requires the no-trailing-":*" ARN specifically for
  # TagResource, UntagResource, and ListTagsForResource.
  statement {
    sid       = "TagNewPreSignUpLogGroupWithApprovedValues"
    effect    = "Allow"
    actions   = ["logs:TagResource"]
    resources = [local.cognito_resource_arns[each.key].log_group_tags]

    dynamic "condition" {
      for_each = local.cognito_application_tags[each.key]
      content {
        test     = "StringEquals"
        variable = "aws:RequestTag/${condition.key}"
        values   = [condition.value]
      }
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = keys(local.cognito_application_tags[each.key])
    }
  }

  statement {
    sid       = "ReadExactPreSignUpLogGroupTags"
    effect    = "Allow"
    actions   = ["logs:ListTagsForResource"]
    resources = [local.cognito_resource_arns[each.key].log_group_tags]
  }

  statement {
    sid       = "ManageExactTaggedPreSignUpLogGroup"
    effect    = "Allow"
    actions   = local.cognito_logs_mutation_actions
    resources = [local.cognito_resource_arns[each.key].log_group]
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
    sid       = "TagExactPreSignUpLogGroupWithApprovedValues"
    effect    = "Allow"
    actions   = ["logs:TagResource"]
    resources = [local.cognito_resource_arns[each.key].log_group_tags]
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
    dynamic "condition" {
      for_each = local.cognito_application_tags[each.key]
      content {
        test     = "StringEqualsIfExists"
        variable = "aws:RequestTag/${condition.key}"
        values   = [condition.value]
      }
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = keys(local.cognito_application_tags[each.key])
    }
  }

  statement {
    sid       = "UntagOnlyNonRequiredPreSignUpLogGroupTags"
    effect    = "Allow"
    actions   = ["logs:UntagResource"]
    resources = [local.cognito_resource_arns[each.key].log_group_tags]
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
    condition {
      test     = "ForAllValues:StringNotEquals"
      variable = "aws:TagKeys"
      values   = keys(local.cognito_application_tags[each.key])
    }
  }

  statement {
    sid       = "DescribeRegionalLogGroupsForProviderRefresh"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  statement {
    sid       = "PassOnlyExactPreSignUpExecutionRoleToLambda"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [local.cognito_resource_arns[each.key].execution_role]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "cognito_apply_boundary" {
  for_each = local.environments

  name        = "pawlocal-${each.key}-cognito-terraform-apply-boundary"
  description = "Maximum permissions for delegated PawLocal ${each.key} Cognito Terraform apply."
  policy      = data.aws_iam_policy_document.cognito_apply_permissions[each.key].json
  tags = {
    project     = "pawlocal"
    environment = each.key
    managedby   = "terraform"
    purpose     = "cognito-terraform-apply-boundary"
  }

  lifecycle {
    precondition {
      condition     = length(data.aws_iam_policy_document.cognito_apply_permissions[each.key].minified_json) <= local.iam_managed_policy_max_bytes
      error_message = "The ${each.key} delegated Cognito apply boundary is ${length(data.aws_iam_policy_document.cognito_apply_permissions[each.key].minified_json)} bytes; it must stay within AWS's 6144-byte managed-policy limit."
    }
  }
}

resource "aws_iam_role" "cognito_terraform" {
  for_each = local.cognito_terraform_role_definitions

  name                 = each.value.role_name
  assume_role_policy   = data.aws_iam_policy_document.cognito_terraform_trust[each.key].json
  description          = "Delegated PawLocal ${each.value.environment} Cognito Terraform ${each.value.purpose} role."
  permissions_boundary = each.value.purpose == "apply" ? aws_iam_policy.cognito_apply_boundary[each.value.environment].arn : null
  max_session_duration = 3600
  tags = {
    project     = "pawlocal"
    environment = each.value.environment
    managedby   = "terraform"
    purpose     = "cognito-terraform-${each.value.purpose}"
  }

  depends_on = [aws_iam_role.github_terraform]
}

resource "aws_iam_role_policy" "cognito_terraform" {
  for_each = local.cognito_terraform_role_definitions

  name = "${each.value.role_name}-permissions"
  role = aws_iam_role.cognito_terraform[each.key].id
  policy = each.value.purpose == "plan" ? (
    data.aws_iam_policy_document.cognito_plan_permissions[each.value.environment].json
    ) : (
    data.aws_iam_policy_document.cognito_apply_permissions[each.value.environment].json
  )
}

data "aws_iam_policy_document" "cognito_pre_sign_up_trust" {
  for_each = local.environments

  statement {
    sid     = "LambdaServiceOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "cognito_pre_sign_up_permissions" {
  for_each = local.environments

  statement {
    sid       = "WriteOnlyMatchingPreSignUpLogStreams"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [local.cognito_resource_arns[each.key].log_stream]
  }
}

resource "aws_iam_role" "cognito_pre_sign_up" {
  for_each = local.environments

  name               = local.cognito_resource_names[each.key].execution_role
  assume_role_policy = data.aws_iam_policy_document.cognito_pre_sign_up_trust[each.key].json
  description        = "PawLocal ${each.key} Cognito pre sign-up Lambda execution role."
  tags = {
    project     = "pawlocal"
    environment = each.key
    managedby   = "terraform"
    purpose     = "cognito-pre-signup"
  }
}

resource "aws_iam_role_policy" "cognito_pre_sign_up" {
  for_each = local.environments

  name   = "${local.cognito_resource_names[each.key].execution_role}-logging"
  role   = aws_iam_role.cognito_pre_sign_up[each.key].id
  policy = data.aws_iam_policy_document.cognito_pre_sign_up_permissions[each.key].json
}
