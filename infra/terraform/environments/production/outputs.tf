output "environment_targets" {
  description = "Production targets and bootstrap handoff identifiers."
  value       = module.pawlocal.targets
}

output "cognito_package_build_id" {
  description = "Plan-bound identifier last applied for the Cognito pre-sign-up Lambda package."
  value       = module.pawlocal.cognito_package_build_id
}
