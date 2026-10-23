locals {
  # Exact producer ownership inventory; never used to authorize reader admission.
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

locals {
  bootstrap_configuration_values = {
    for environment in keys(local.environments) : environment => merge({
      "iam/terraform-plan-role-arn"   = aws_iam_role.github_terraform["${environment}-plan"].arn
      "iam/terraform-apply-role-arn"  = aws_iam_role.github_terraform["${environment}-apply"].arn
      "aws/account-id"                = data.aws_caller_identity.current.account_id
      "terraform/plan-bucket"         = aws_s3_bucket.plan_transfer.bucket
      "iam/frontend-publish-role-arn" = aws_iam_role.identity_app["${environment}_frontend"].arn
      }, environment == "development" ? (
      var.development_lightsail_principal_arn == "" ? {} : { "iam/runtime-role-arn" = aws_iam_role.development_runtime[0].arn }
      ) : (
      var.production_lightsail_principal_arn == "" ? {} : { "iam/runtime-role-arn" = aws_iam_role.production_runtime[0].arn }
    ))
  }
  bootstrap_configuration_parameters = merge([
    for environment, values in local.bootstrap_configuration_values : {
      for suffix, value in values : "${environment}/${suffix}" => {
        environment = environment
        suffix      = suffix
        value       = value
      }
    }
  ]...)
  application_configuration_suffixes = setsubtract(local.configuration_parameter_suffixes, toset([
    "iam/terraform-plan-role-arn", "iam/terraform-apply-role-arn", "aws/account-id",
    "terraform/plan-bucket", "iam/frontend-publish-role-arn", "iam/runtime-role-arn"
  ]))
  application_configuration_arns = {
    for environment in keys(local.environments) : environment => [
      for suffix in sort(tolist(local.application_configuration_suffixes)) :
      "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/pawlocal/${environment}/config/${suffix}"
    ]
  }
}

resource "aws_ssm_parameter" "configuration" {
  for_each = local.bootstrap_configuration_parameters

  name        = "/pawlocal/${each.value.environment}/config/${each.value.suffix}"
  description = "Terraform-generated PawLocal ${each.value.environment} ${each.value.suffix}."
  type        = "String"
  tier        = "Standard"
  value       = each.value.value
  # Omit overwrite: the pinned provider refuses to adopt an existing key on
  # creation, while later updates remain owned by this resource's state.
  tags = {
    environment            = each.value.environment
    purpose                = "configuration"
    "configuration-access" = "github-public"
  }
}
