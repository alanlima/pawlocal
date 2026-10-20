locals {
  bootstrap = data.terraform_remote_state.iam_bootstrap.outputs
  policies  = local.bootstrap.identity_managed_policy_arns
  role_names = {
    development_frontend = "pawlocal-development-github-deploy"
    production_frontend  = "pawlocal-production-github-deploy"
    development_runtime  = "pawlocal-development-dsql-runtime"
  }
  selected_roles = {
    for key, name in local.role_names : key => name
    if var.target_environment == "development" ? key != "production_frontend" : key == "production_frontend"
  }
  selected_policies = {
    for key, arn in local.policies : key => arn
    if contains(keys(local.selected_roles), key)
  }
}

data "terraform_remote_state" "iam_bootstrap" {
  backend = "s3"
  config = {
    bucket       = var.terraform_state_bucket_name
    key          = "pawlocal/iam-bootstrap/terraform.tfstate"
    region       = var.aws_region
    use_lockfile = true
  }
}

data "aws_iam_role" "app" {
  for_each = local.selected_roles
  name     = each.value
}

resource "aws_iam_role_policy_attachment" "app" {
  for_each   = local.selected_roles
  role       = data.aws_iam_role.app[each.key].name
  policy_arn = local.selected_policies[each.key]

  lifecycle {
    precondition {
      condition     = data.aws_iam_role.app[each.key].arn == local.bootstrap.identity_app_role_arns[each.key]
      error_message = "The selected IAM role ARN must match the exact role ARN managed by the IAM bootstrap state."
    }
  }
}
