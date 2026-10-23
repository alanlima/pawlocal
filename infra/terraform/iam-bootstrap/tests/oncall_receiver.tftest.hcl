provider "aws" {
  alias                       = "oncall_test"
  region                      = "ap-southeast-2"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}
override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "111111111111" }
}
override_data {
  target = data.aws_partition.current
  values = { partition = "aws" }
}
variables {
  terraform_state_bucket_name = "fixture-state-bucket-x"
  github_repository           = "example/pawlocal"
  github_owner_id             = "1"
  github_repository_id        = "2"
  manage_github_oidc_provider = true
  route53_zone_id             = "ZFIXTURE000000"
  domain_name                 = "fixture.example"
}
run "oncall_identities_default_off" {
  command   = plan
  providers = { aws = aws.oncall_test }
  assert {
    condition     = length(aws_iam_role.oncall_receiver) == 0 && length(aws_iam_role.oncall_terraform) == 0
    error_message = "Default bootstrap must add no receiver identities or policies."
  }
}
run "development_only_identity_and_permission_envelope" {
  command   = plan
  providers = { aws = aws.oncall_test }
  variables { oncall_environments = ["development"] }
  assert {
    condition     = toset(keys(aws_iam_role.oncall_terraform)) == toset(["development-plan", "development-apply"]) && keys(aws_iam_role.oncall_receiver) == ["development"]
    error_message = "Development opt-in must not create production identities."
  }
  assert {
    condition     = length(jsondecode(local.oncall_runtime_policies.development).Statement) == 2 && jsondecode(local.oncall_runtime_policies.development).Statement[1].Resource == local.oncall_arns.development.secrets
    error_message = "Runtime boundary must allow only its two SSM secrets and logs, without invented KMS wildcard."
  }
  assert {
    condition     = length(data.aws_iam_policy_document.oncall_apply["development"].minified_json) <= 6144
    error_message = "Delegated apply boundary must fit AWS policy size."
  }
  assert {
    condition = alltrue([
      for statement in jsondecode(data.aws_iam_policy_document.oncall_plan["development"].json).Statement :
      (!contains(try(tolist(statement.Action), [statement.Action]), "ssm:GetParameter") || statement.Resource == local.oncall_arns.development.public_url) &&
      !contains(try(tolist(statement.Action), [statement.Action]), "kms:Decrypt")
    ])
    error_message = "Plan/apply roles must never read decrypted runtime secrets."
  }
}
run "explicit_existing_key_has_exact_ssm_decrypt_context" {
  command   = plan
  providers = { aws = aws.oncall_test }
  variables {
    oncall_environments          = ["development"]
    oncall_receiver_kms_key_arns = { development = "arn:aws:kms:ap-southeast-2:111111111111:key/11111111-1111-1111-1111-111111111111" }
  }
  assert {
    condition = (
      jsondecode(local.oncall_runtime_policies.development).Statement[2].Resource == [var.oncall_receiver_kms_key_arns.development] &&
      jsondecode(local.oncall_runtime_policies.development).Statement[2].Condition.StringEquals["kms:EncryptionContext:PARAMETER_ARN"] == local.oncall_arns.development.secrets
    )
    error_message = "Explicit key grants need exact key and matching parameter encryption context."
  }
}
run "reject_unknown_oncall_environment" {
  command   = plan
  providers = { aws = aws.oncall_test }
  variables { oncall_environments = ["staging"] }
  expect_failures = [var.oncall_environments]
}
