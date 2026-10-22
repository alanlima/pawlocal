output "terraform_role_arns" {
  description = "GitHub OIDC Terraform plan and apply role ARNs for development and production. These identifiers are safe for GitHub variables."
  value       = { for key, role in aws_iam_role.github_terraform : key => role.arn }
}

output "github_oidc_provider_arn" {
  description = "GitHub OIDC provider managed or read by this bootstrap state."
  value       = local.oidc_arn
}

output "aws_account_id" {
  description = "AWS account targeted by the bootstrap state."
  value       = data.aws_caller_identity.current.account_id
}

output "plan_transfer_bucket_name" {
  description = "Private Terraform plan transfer bucket; plan and apply roles have environment-prefix-only access."
  value       = local.plan_transfer_bucket_name
}

output "legacy_terraform_role_arns" {
  description = "GitHub OIDC plan/apply role ARNs for the legacy combined-state operations workflow."
  value       = { for key, role in aws_iam_role.legacy_terraform : key => role.arn }
}

output "cognito_terraform_role_arns" {
  description = "Delegated Cognito Terraform role ARNs, keyed by environment and plan/apply purpose. Verification evidence only; workflows construct deterministic ARNs instead of consuming this output."
  value = {
    for environment in keys(local.environments) : environment => {
      plan  = aws_iam_role.cognito_terraform["${environment}-plan"].arn
      apply = aws_iam_role.cognito_terraform["${environment}-apply"].arn
    }
  }
}

output "cognito_pre_sign_up_role_arns" {
  description = "Cognito pre sign-up Lambda execution role ARNs, keyed by environment. Verification evidence only; environment Terraform derives the deterministic ARN."
  value       = { for environment, role in aws_iam_role.cognito_pre_sign_up : environment => role.arn }
}

output "configuration_reader_role_arns" {
  description = "Dedicated configuration-reader role ARNs for initial matching protected apply and release Environment setup."
  value       = { for environment, role in aws_iam_role.configuration_reader : environment => role.arn }
}
