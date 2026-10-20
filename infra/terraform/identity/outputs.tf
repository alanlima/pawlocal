output "role_arns" {
  description = "Exact bootstrap-owned application role ARNs whose fixed policies were attached by this state."
  value = merge(
    contains(keys(data.aws_iam_role.app), "development_frontend") ? { development_frontend_deploy = data.aws_iam_role.app["development_frontend"].arn } : {},
    contains(keys(data.aws_iam_role.app), "production_frontend") ? { production_frontend_deploy = data.aws_iam_role.app["production_frontend"].arn } : {},
    contains(keys(data.aws_iam_role.app), "development_runtime") ? { development_dsql_runtime = data.aws_iam_role.app["development_runtime"].arn } : {}
  )
}
