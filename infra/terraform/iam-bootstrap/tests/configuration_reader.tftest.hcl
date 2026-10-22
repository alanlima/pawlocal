override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "111111111111" }
}

override_data {
  target = data.aws_partition.current
  values = { partition = "aws" }
}

override_data {
  target = data.aws_iam_openid_connect_provider.github[0]
  values = { arn = "arn:aws:iam::111111111111:oidc-provider/token.actions.githubusercontent.com" }
}

provider "aws" {
  alias                       = "test"
  region                      = "ap-southeast-2"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

run "configuration_readers_are_exact_and_isolated" {
  command = plan

  providers = { aws = aws.test }

  variables {
    terraform_state_bucket_name = "fixture-state-bucket-x"
    github_repository           = "example/pawlocal"
    github_owner_id             = "1"
    github_repository_id        = "2"
    route53_zone_id             = "ZFIXTURE000000"
    domain_name                 = "fixture.example"
  }

  assert {
    condition     = toset(keys(aws_iam_role.configuration_reader)) == toset(["development", "production"])
    error_message = "Only dedicated development and production configuration readers may exist."
  }

  assert {
    condition = alltrue([
      for environment, role in aws_iam_role.configuration_reader :
      role.name == "pawlocal-${environment}-configuration-reader" &&
      role.max_session_duration == 3600 &&
      role.tags.environment == environment &&
      role.tags.purpose == "configuration-read"
    ])
    error_message = "Reader identity, session lifetime and environment tags must remain deterministic."
  }

  assert {
    condition = alltrue([
      for environment, trust in data.aws_iam_policy_document.configuration_reader_trust :
      length(jsondecode(trust.minified_json).Statement) == 1 &&
      toset(flatten([jsondecode(trust.minified_json).Statement[0].Action])) == toset(["sts:AssumeRoleWithWebIdentity"]) &&
      jsondecode(trust.minified_json).Statement[0].Principal.Federated == "arn:aws:iam::111111111111:oidc-provider/token.actions.githubusercontent.com" &&
      jsondecode(trust.minified_json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" &&
      jsondecode(trust.minified_json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example@1/pawlocal@2:environment:${environment}-apply"
    ])
    error_message = "Reader trust must bind exact provider, audience, immutable repository IDs and matching protected apply Environment."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.configuration_reader :
      length(jsondecode(policy.minified_json).Statement) == 1 &&
      toset(flatten([jsondecode(policy.minified_json).Statement[0].Action])) == toset(["ssm:GetParameter"]) &&
      length(jsondecode(policy.minified_json).Statement[0].Resource) == 18 &&
      alltrue([
        for arn in jsondecode(policy.minified_json).Statement[0].Resource :
        startswith(arn, "arn:aws:ssm:ap-southeast-2:111111111111:parameter/pawlocal/${environment}/config/") &&
        !strcontains(arn, "*") && !strcontains(arn, "/secrets/")
      ])
    ])
    error_message = "Readers may only GetParameter for the 18 exact local String keys; no discovery, writes, decryption or cross-environment scope."
  }

  assert {
    condition = local.configuration_parameter_suffixes == toset([
      "iam/terraform-plan-role-arn", "iam/terraform-apply-role-arn", "aws/account-id", "terraform/plan-bucket",
      "iam/frontend-publish-role-arn", "iam/runtime-role-arn", "frontend/base-url", "api/health-url", "frontend/bucket",
      "frontend/cloudfront-distribution-id", "frontend/cloudfront-distribution-arn", "frontend/cloudfront-oac-arn",
      "auth/client-id", "api/base-url", "auth/domain", "auth/redirect-uri", "auth/logout-uri", "auth/scopes"
    ])
    error_message = "IAM reader keys must remain in parity with the approved 18-key inventory."
  }
}
