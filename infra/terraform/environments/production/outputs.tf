output "environment_targets" {
  description = "Non-secret deployment targets for the isolated production state."
  value       = module.fullstack.environment_targets
}

output "oac_id" {
  description = "Production CloudFront origin access control ID for reviewed IAM policy scoping."
  value       = module.fullstack.environment_targets[local.environment].oac_id
}

output "oac_arn" {
  description = "Production CloudFront origin access control ARN for reviewed IAM policy scoping."
  value       = module.fullstack.environment_targets[local.environment].oac_arn
}
