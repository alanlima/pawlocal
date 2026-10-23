variable "oncall_environments" {
  description = "Explicitly approved receiver identity environments. Empty keeps all new identities disabled."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for environment in var.oncall_environments : contains(["development", "production"], environment)])
    error_message = "oncall_environments accepts only development and production."
  }
}

variable "oncall_receiver_kms_key_arns" {
  description = "Optional exact existing KMS key per enabled environment. Empty relies on aws/ssm policy and needs a live role-boundary decrypt check before activation; no key is created."
  type        = map(string)
  default     = {}
  validation {
    condition = alltrue([
      for environment, key_arn in var.oncall_receiver_kms_key_arns :
      contains(["development", "production"], environment) && can(regex("^arn:${data.aws_partition.current.partition}:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:key/[0-9a-f-]{36}$", key_arn))
    ])
    error_message = "An explicitly supplied KMS key must belong to an approved environment in this account and region."
  }
}

locals {
  oncall_environments = { for environment, config in local.environments : environment => config if contains(var.oncall_environments, environment) }
  oncall_roles = merge(
    { for environment in var.oncall_environments : "${environment}-plan" => { environment = environment, purpose = "plan" } },
    { for environment in var.oncall_environments : "${environment}-apply" => { environment = environment, purpose = "apply" } }
  )
  oncall_arns = { for environment in var.oncall_environments : environment => {
    function   = "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${var.project_name}-${environment}-oncall-receiver"
    role       = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${environment}-oncall-receiver"
    logs       = "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-${environment}-oncall-receiver"
    public_url = "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/${environment}/config/oncall/webhook-url"
    secrets = [for suffix in ["grafana/webhook-hmac", "oncall/dispatch-app-private-key"] :
      "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/${environment}/secrets/${suffix}"
    ]
  } }
  oncall_read_actions = [
    "lambda:GetFunction", "lambda:GetFunctionCodeSigningConfig", "lambda:GetPolicy", "lambda:ListTags",
    "lambda:ListVersionsByFunction", "lambda:GetFunctionUrlConfig", "lambda:GetFunctionConcurrency"
  ]
  oncall_runtime_policies = { for environment, arns in local.oncall_arns : environment => jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Sid = "WriteOnlyReceiverLogs", Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${arns.logs}:log-stream:*"] },
      { Sid = "ReadOnlyTwoRuntimeSecrets", Effect = "Allow", Action = ["ssm:GetParameter"], Resource = arns.secrets }
      ], contains(keys(var.oncall_receiver_kms_key_arns), environment) ? [
      { Sid = "DecryptOnlyTwoSSMSecrets", Effect = "Allow", Action = ["kms:Decrypt"], Resource = [var.oncall_receiver_kms_key_arns[environment]], Condition = {
        StringEquals = { "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com", "kms:EncryptionContext:PARAMETER_ARN" = arns.secrets }
      } }
    ] : [])
  }) }
}

data "aws_iam_policy_document" "oncall_plan" {
  for_each = local.oncall_environments
  statement {
    actions   = local.oncall_read_actions
    resources = [local.oncall_arns[each.key].function]
  }
  statement {
    actions   = ["logs:ListTagsForResource"]
    resources = [local.oncall_arns[each.key].logs]
  }
  statement {
    actions   = ["iam:GetRolePolicy"]
    resources = [local.oncall_arns[each.key].role]
  }
  statement {
    sid       = "ReadOnlyPublicReceiverUrl"
    actions   = ["ssm:GetParameter", "ssm:ListTagsForResource"]
    resources = [local.oncall_arns[each.key].public_url]
  }
  statement {
    sid       = "DescribeRegionalParameterMetadata"
    actions   = ["ssm:DescribeParameters"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }
  # Same documented provider-refresh limitation as DEC-009. This is metadata,
  # never log content; an exact LogGroupNamePrefix is not enforceable by IAM.
  statement {
    sid       = "DescribeRegionalLogGroupMetadata"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }
}

data "aws_iam_policy_document" "oncall_apply" {
  for_each                = local.oncall_environments
  source_policy_documents = [data.aws_iam_policy_document.oncall_plan[each.key].json]
  statement {
    sid       = "CreateOnlyTaggedReceiver"
    actions   = ["lambda:CreateFunction", "lambda:TagResource"]
    resources = [local.oncall_arns[each.key].function]
    dynamic "condition" {
      for_each = { project = var.project_name, environment = each.key, managedby = "terraform", component = "fullstack-mvp", workload = "application", costcenter = "personal" }
      content {
        test     = "StringEquals"
        variable = "aws:RequestTag/${condition.key}"
        values   = [condition.value]
      }
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["project", "environment", "managedby", "component", "workload", "costcenter"]
    }
  }
  statement {
    sid = "ManageOnlyOwnedReceiver"
    actions = [
      "lambda:DeleteFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:RemovePermission",
      "lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig", "lambda:DeleteFunctionUrlConfig",
      "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency"
    ]
    resources = [local.oncall_arns[each.key].function]
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
  }
  # The exact function needs public URL invoke grants. The trusted Terraform
  # apply role can add public grants on this one function; plan review must
  # enforce FunctionUrlAuthType/InvokedViaFunctionUrl. No agent holds this role.
  statement {
    sid       = "GrantOnlyPublicReceiverInvocation"
    actions   = ["lambda:AddPermission"]
    resources = [local.oncall_arns[each.key].function]
    condition {
      test     = "StringEquals"
      variable = "lambda:Principal"
      values   = ["*"]
    }
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:TagResource", "logs:UntagResource"]
    resources = [local.oncall_arns[each.key].logs, "${local.oncall_arns[each.key].logs}:*"]
  }
  statement {
    actions   = ["iam:PutRolePolicy", "iam:DeleteRolePolicy"]
    resources = [local.oncall_arns[each.key].role]
    # IAM cannot restrict inline-policy names. The immutable bootstrap-owned
    # execution-role boundary caps every policy the delegated writer can set.
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [local.oncall_arns[each.key].role]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
  statement {
    sid       = "PublishOnlyPublicReceiverUrl"
    actions   = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource"]
    resources = [local.oncall_arns[each.key].public_url]
  }
}

data "aws_iam_policy_document" "oncall_trust" {
  for_each = local.oncall_roles
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.github_terraform[each.key].arn]
    }
  }
}
resource "aws_iam_policy" "oncall_apply_boundary" {
  for_each = local.oncall_environments
  name     = "${var.project_name}-${each.key}-oncall-terraform-apply-boundary"
  policy   = data.aws_iam_policy_document.oncall_apply[each.key].json
  lifecycle {
    precondition {
      condition     = length(data.aws_iam_policy_document.oncall_apply[each.key].minified_json) <= 6144
      error_message = "On-call apply boundary exceeds the managed-policy size limit."
    }
  }
}
resource "aws_iam_role" "oncall_terraform" {
  for_each             = local.oncall_roles
  name                 = "${var.project_name}-${each.value.environment}-oncall-terraform-${each.value.purpose}"
  assume_role_policy   = data.aws_iam_policy_document.oncall_trust[each.key].json
  permissions_boundary = each.value.purpose == "apply" ? aws_iam_policy.oncall_apply_boundary[each.value.environment].arn : null
  max_session_duration = 3600
  tags                 = { environment = each.value.environment, purpose = "oncall-terraform-${each.value.purpose}" }
}
resource "aws_iam_role_policy" "oncall_terraform" {
  for_each = local.oncall_roles
  name     = "${var.project_name}-${each.value.environment}-oncall-terraform-${each.value.purpose}"
  role     = aws_iam_role.oncall_terraform[each.key].id
  policy   = each.value.purpose == "plan" ? data.aws_iam_policy_document.oncall_plan[each.value.environment].json : data.aws_iam_policy_document.oncall_apply[each.value.environment].json
}
resource "aws_iam_role_policy" "oncall_assume" {
  for_each = local.oncall_roles
  name     = "${var.project_name}-${each.value.environment}-assume-oncall-${each.value.purpose}"
  role     = aws_iam_role.github_terraform[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["sts:AssumeRole"], Resource = [aws_iam_role.oncall_terraform[each.key].arn]
  }] })
}
resource "aws_iam_policy" "oncall_runtime_boundary" {
  for_each = local.oncall_environments
  name     = "${var.project_name}-${each.key}-oncall-runtime-boundary"
  policy   = local.oncall_runtime_policies[each.key]
}
resource "aws_iam_role" "oncall_receiver" {
  for_each             = local.oncall_environments
  name                 = "${var.project_name}-${each.key}-oncall-receiver"
  permissions_boundary = aws_iam_policy.oncall_runtime_boundary[each.key].arn
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["sts:AssumeRole"], Principal = { Service = "lambda.amazonaws.com" }
  }] })
  tags = { environment = each.key, purpose = "oncall-receiver" }
}
