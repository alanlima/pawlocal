output "terraform_role_arns" {
  description = "GitHub OIDC Terraform plan, apply, and recovery role ARNs. These identifiers are safe for GitHub Environment variables."
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
  value       = aws_s3_bucket.plan_transfer.bucket
}
