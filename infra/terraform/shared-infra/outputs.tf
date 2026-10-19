output "github_deploy_role_arns" {
  description = "GitHub OIDC frontend publisher roles by environment."
  value = {
    development = aws_iam_role.github_deploy_development.arn
    production  = aws_iam_role.github_deploy.arn
  }
}

output "github_terraform_deploy_role_arns" {
  description = "GitHub OIDC Terraform application-release roles by environment."
  value       = { for environment, role in aws_iam_role.github_terraform_deploy : environment => role.arn }
}

output "github_oidc_provider_arn" {
  description = "Terraform-managed shared GitHub Actions OIDC provider ARN."
  value       = aws_iam_openid_connect_provider.github[0].arn
}
