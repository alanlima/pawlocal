variable "oncall_receiver" {
  description = "Explicit reviewed receiver opt-in. Null creates no receiver resources. Public operator configuration only; no secret payloads."
  type = object({
    app_id           = string
    installation_id  = string
    repository_id    = string
    repository       = string
    allowed_services = set(string)
    allowed_alerts   = optional(set(string), [])
    kms_key_arn      = optional(string)
  })
  default = null
  validation {
    condition = var.oncall_receiver == null ? true : (
      alltrue([for value in [var.oncall_receiver.app_id, var.oncall_receiver.installation_id, var.oncall_receiver.repository_id] : can(regex("^[1-9][0-9]{0,15}$", value))]) &&
      try(tonumber(var.oncall_receiver.repository_id) <= 9007199254740991, false) &&
      can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$", var.oncall_receiver.repository)) &&
      !contains([".", ".."], try(split("/", var.oncall_receiver.repository)[1], "")) &&
      length(var.oncall_receiver.allowed_services) >= 1 && length(var.oncall_receiver.allowed_services) <= 10 &&
      try(length(var.oncall_receiver.allowed_alerts), 0) <= 20 &&
      alltrue([for value in setunion(var.oncall_receiver.allowed_services, coalesce(var.oncall_receiver.allowed_alerts, [])) : can(regex("^[a-z0-9][a-z0-9-]{0,99}$", value))]) &&
      (var.oncall_receiver.kms_key_arn == null || can(regex("^arn:${data.aws_partition.current.partition}:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:key/[0-9a-f-]{36}$", var.oncall_receiver.kms_key_arn)))
    )
    error_message = "Receiver configuration needs safe numeric App/installation/repository IDs, bounded service/alert allow-lists and, when supplied, an exact existing KMS key in this account/region."
  }
}

locals {
  oncall_enabled  = var.oncall_receiver != null
  oncall_name     = "${var.project_name}-${var.environment}-oncall-receiver"
  oncall_role_arn = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${local.oncall_name}"
  oncall_secret_arns = [for suffix in ["grafana/webhook-hmac", "oncall/dispatch-app-private-key"] :
    "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/${var.environment}/secrets/${suffix}"
  ]
}

resource "aws_iam_role_policy" "oncall_runtime" {
  count    = local.oncall_enabled ? 1 : 0
  provider = aws.oncall_deployment
  name     = "${var.project_name}-${var.environment}-oncall-runtime"
  role     = local.oncall_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.oncall_name}:log-stream:*"] },
      { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = local.oncall_secret_arns }
      ], var.oncall_receiver.kms_key_arn == null ? [] : [
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = [var.oncall_receiver.kms_key_arn], Condition = {
        StringEquals = { "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com", "kms:EncryptionContext:PARAMETER_ARN" = local.oncall_secret_arns }
      } }
    ])
  })
}

module "oncall_receiver" {
  count     = local.oncall_enabled ? 1 : 0
  source    = "terraform-aws-modules/lambda/aws"
  version   = "= 8.12.0"
  providers = { aws = aws.oncall_deployment }

  function_name                     = local.oncall_name
  description                       = "Authenticate bounded Grafana events and request fixed GitHub incident dispatch."
  handler                           = "index.handler"
  runtime                           = "nodejs24.x"
  timeout                           = 20
  memory_size                       = 128
  reserved_concurrent_executions    = 2
  create_role                       = false
  lambda_role                       = local.oncall_role_arn
  source_path                       = "${path.module}/lambda/incident-receiver/index.mjs"
  artifacts_dir                     = "${path.root}/.terraform/lambda-builds"
  recreate_missing_package          = true
  trigger_on_package_timestamp      = false
  ignore_source_code_hash           = true
  cloudwatch_logs_retention_in_days = 14
  create_sam_metadata               = false
  allowed_triggers                  = {}
  environment_variables = {
    PAWLOCAL_PROJECT_NAME             = var.project_name
    PAWLOCAL_ONCALL_ENVIRONMENT       = var.environment
    PAWLOCAL_DISPATCH_APP_ID          = var.oncall_receiver.app_id
    PAWLOCAL_DISPATCH_INSTALLATION_ID = var.oncall_receiver.installation_id
    PAWLOCAL_DISPATCH_REPOSITORY_ID   = var.oncall_receiver.repository_id
    PAWLOCAL_DISPATCH_REPOSITORY      = var.oncall_receiver.repository
    PAWLOCAL_ONCALL_ALLOWED_SERVICES  = jsonencode(sort(tolist(var.oncall_receiver.allowed_services)))
    PAWLOCAL_ONCALL_ALLOWED_ALERTS    = var.oncall_receiver.allowed_alerts == null || length(var.oncall_receiver.allowed_alerts) == 0 ? "[]" : jsonencode(sort(tolist(var.oncall_receiver.allowed_alerts)))
  }
  tags       = local.common_tags
  depends_on = [aws_iam_role_policy.oncall_runtime]
}

resource "aws_lambda_function_url" "oncall_receiver" {
  count              = local.oncall_enabled ? 1 : 0
  provider           = aws.oncall_deployment
  function_name      = module.oncall_receiver[0].lambda_function_name
  authorization_type = "NONE"
}
resource "aws_lambda_permission" "oncall_url" {
  count                  = local.oncall_enabled ? 1 : 0
  provider               = aws.oncall_deployment
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = module.oncall_receiver[0].lambda_function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
resource "aws_lambda_permission" "oncall_via_url" {
  count                    = local.oncall_enabled ? 1 : 0
  provider                 = aws.oncall_deployment
  statement_id             = "AllowInvokeOnlyViaFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = module.oncall_receiver[0].lambda_function_name
  principal                = "*"
  invoked_via_function_url = true
}

resource "aws_ssm_parameter" "oncall_webhook_url" {
  count       = local.oncall_enabled ? 1 : 0
  provider    = aws.oncall_deployment
  name        = "/${var.project_name}/${var.environment}/config/oncall/webhook-url"
  description = "Public independent Grafana receiver endpoint; never an ingestion credential."
  type        = "String"
  value       = aws_lambda_function_url.oncall_receiver[0].function_url
  tags = merge(local.common_tags, {
    "configuration-access" = "github-public"
  })
}

output "oncall_receiver_url" {
  description = "Public receiver URL after separate owner-approved opt-in/apply. Null while disabled."
  value       = one(aws_lambda_function_url.oncall_receiver[*].function_url)
}
