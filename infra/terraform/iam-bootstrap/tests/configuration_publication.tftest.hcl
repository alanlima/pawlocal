override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "111111111111" }
}

override_data {
  target = data.aws_partition.current
  values = { partition = "aws" }
}

provider "aws" {
  alias                       = "test"
  region                      = "ap-southeast-2"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
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

run "foundation_publishes_only_existing_bootstrap_values" {
  command   = plan
  providers = { aws = aws.test }

  assert {
    condition = length(aws_ssm_parameter.configuration) == 10 && alltrue([
      for key, parameter in aws_ssm_parameter.configuration :
      parameter.type == "String" && parameter.tier == "Standard" &&
      startswith(parameter.name, "/pawlocal/${local.bootstrap_configuration_parameters[key].environment}/config/") &&
      !endswith(parameter.name, "/iam/runtime-role-arn") &&
      !strcontains(parameter.name, "/api/") && !strcontains(parameter.name, "/auth/") && !strcontains(parameter.name, "/frontend/") &&
      parameter.overwrite == null
    ])
    error_message = "Foundation owns only its five existing non-secret bootstrap keys per environment and must not adopt colliding keys."
  }

  assert {
    condition = alltrue([
      for environment in ["development", "production"] :
      aws_ssm_parameter.configuration["${environment}/aws/account-id"].value == "111111111111" &&
      aws_ssm_parameter.configuration["${environment}/terraform/plan-bucket"].value == aws_s3_bucket.plan_transfer.bucket
    ])
    error_message = "Bootstrap values must be actual current-account and managed-resource attributes."
  }

  assert {
    condition = alltrue([
      for policy in concat(values(data.aws_iam_policy_document.role_permissions), values(data.aws_iam_policy_document.environment_apply_boundary)) :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "ssm:DescribeParameters") &&
        toset(flatten([statement.Action])) == toset(["ssm:DescribeParameters"]) &&
        toset(flatten([statement.Resource])) == toset(["*"]) &&
        toset(keys(statement.Condition)) == toset(["StringEquals"]) &&
        toset(keys(statement.Condition.StringEquals)) == toset(["aws:RequestedRegion"]) &&
        statement.Condition.StringEquals["aws:RequestedRegion"] == var.aws_region &&
        statement.Condition.StringEquals["aws:RequestedRegion"] != "us-east-1"
      ]) == 1
    ])
    error_message = "Metadata access must be one exact action, wildcard resource and strict configured-region condition; another region and IfExists must not pass."
  }

  assert {
    condition = alltrue([
      for key, policy in data.aws_iam_policy_document.role_permissions :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if toset(flatten([statement.Action])) == toset(["ssm:GetParameter", "ssm:ListTagsForResource"]) &&
        toset(flatten([statement.Resource])) == toset(local.application_configuration_arns[local.role_definitions[key].environment]) &&
        length(flatten([statement.Resource])) == 12 &&
        alltrue([for arn in flatten([statement.Resource]) : !strcontains(arn, "*") && !strcontains(arn, "/iam/") && !strcontains(arn, "/aws/") && !strcontains(arn, "/terraform/")])
      ]) == 1 &&
      !strcontains(policy.minified_json, "ssm:GetParameterHistory") && !strcontains(policy.minified_json, "ssm:GetParametersByPath") &&
      !strcontains(policy.minified_json, "ssm:PutParameter") && !strcontains(policy.minified_json, "ssm:DeleteParameter")
    ])
    error_message = "Baseline identities may refresh only exact matching application keys; application state owns exact-key mutation authority."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.configuration_reader :
      length(jsondecode(policy.minified_json).Statement) == 1 &&
      toset(flatten([jsondecode(policy.minified_json).Statement[0].Action])) == toset(["ssm:GetParameter"]) &&
      length(flatten([jsondecode(policy.minified_json).Statement[0].Resource])) == 18
    ])
    error_message = "Dedicated configuration readers must not acquire metadata, mutation, history, by-path or decryption permissions."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      length(policy.minified_json) <= 6100 &&
      alltrue([
        for statement in jsondecode(policy.minified_json).Statement :
        alltrue([for action in flatten([statement.Action]) : !strcontains(action, "*")])
        if anytrue([for action in flatten([statement.Action]) : startswith(action, "ssm:")])
      ]) &&
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "ssm:PutParameter") &&
        toset(flatten([statement.Resource])) == toset([for component in ["api", "auth", "frontend"] : "arn:aws:ssm:ap-southeast-2:111111111111:parameter/pawlocal/${environment}/config/${component}/*"])
      ]) == 1
    ])
    error_message = "Size-safe boundaries must retain only matching application components, without SSM action wildcards or bootstrap-key mutation."
  }

  # Mechanically enumerate every added non-SSM literal permission pair. There
  # is no catch-all authorization simulator: any unexpected pair fails closed.
  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      setsubtract(toset(flatten([
        for statement in jsondecode(policy.minified_json).Statement : [
          for action in flatten([statement.Action]) : [
            for resource in flatten([statement.Resource]) : jsonencode({ effect = statement.Effect, action = action, resource = resource, condition = try(statement.Condition, {}) })
          ] if !startswith(action, "ssm:")
        ]
        ])), toset(flatten([
        for statement in jsondecode(file("${path.module}/tests/fixtures/boundary-before-206.json")).policies[environment].Statement : [
          for action in flatten([statement.Action]) : [
            for resource in flatten([statement.Resource]) : jsonencode({ effect = statement.Effect, action = action, resource = resource, condition = try(statement.Condition, {}) })
          ]
        ]
        ]))) == toset(concat(
        # S3's existing trailing * already matches /object paths. These five
        # pairs only repeat an already permitted ARN subset (not a type guess).
        [for action in ["s3:GetBucket*", "s3:Get*Configuration", "s3:ListBucket", "s3:ListTagsForResource", "s3:PutBucketTagging"] : jsonencode({ effect = "Allow", action = action, resource = "arn:aws:s3:::pawlocal-${environment}-*/*", condition = {} })],
        # CloudFront actions authorize only CloudFront distribution resources;
        # the named other-service ARN pairs below are explicitly unsupported.
        [for resource in ["arn:aws:cognito-idp:ap-southeast-2:111111111111:userpool/*", "arn:aws:lightsail:ap-southeast-2:111111111111:Certificate/*", "arn:aws:lightsail:ap-southeast-2:111111111111:ContainerService/*"] : jsonencode({ effect = "Allow", action = "cloudfront:TagResource", resource = resource, condition = { StringEquals = { "aws:ResourceTag/project" = "pawlocal", "aws:ResourceTag/environment" = environment, "aws:RequestTag/project" = "pawlocal", "aws:RequestTag/environment" = environment } } })],
        [for action in ["cognito-idp:TagResource", "lightsail:TagResource"] : jsonencode({ effect = "Allow", action = action, resource = "arn:aws:cloudfront::111111111111:distribution/*", condition = { StringEquals = { "aws:ResourceTag/project" = "pawlocal", "aws:ResourceTag/environment" = environment, "aws:RequestTag/project" = "pawlocal", "aws:RequestTag/environment" = environment } } })],
        flatten([for action in ["cloudfront:DeleteDistribution", "cloudfront:UpdateDistribution"] : [for resource in ["arn:aws:dsql:ap-southeast-2:111111111111:cluster/*", "arn:aws:lightsail:ap-southeast-2:111111111111:Certificate/*", "arn:aws:lightsail:ap-southeast-2:111111111111:ContainerService/*"] : jsonencode({ effect = "Allow", action = action, resource = resource, condition = { StringEquals = { "aws:ResourceTag/project" = "pawlocal", "aws:ResourceTag/environment" = environment } } })]]),
        [for action in ["dsql:DbConnectAdmin", "dsql:DeleteCluster", "dsql:UpdateCluster", "dsql:PutClusterPolicy", "lightsail:*ContainerService*", "lightsail:DeleteCertificate"] : jsonencode({ effect = "Allow", action = action, resource = "arn:aws:cloudfront::111111111111:distribution/*", condition = { StringEquals = { "aws:ResourceTag/project" = "pawlocal", "aws:ResourceTag/environment" = environment } } })]
      )) &&
      length(setsubtract(toset(flatten([
        for statement in jsondecode(file("${path.module}/tests/fixtures/boundary-before-206.json")).policies[environment].Statement : [
          for action in flatten([statement.Action]) : [for resource in flatten([statement.Resource]) : jsonencode({ effect = statement.Effect, action = action, resource = resource, condition = try(statement.Condition, {}) })]
        ]
        ])), toset(flatten([
        for statement in jsondecode(policy.minified_json).Statement : [
          for action in flatten([statement.Action]) : [for resource in flatten([statement.Resource]) : jsonencode({ effect = statement.Effect, action = action, resource = resource, condition = try(statement.Condition, {}) })]
        ]
      ])))) == 0
    ])
    error_message = "Compaction must retain every prior pair and add exactly the 22 sourced unsupported/redundant pairs; any other authority change is forbidden."
  }
}

run "runtime_handoff_adds_only_actual_runtime_keys" {
  command   = plan
  providers = { aws = aws.test }

  variables {
    development_lightsail_principal_arn = "arn:aws:iam::111111111111:role/fixture-development-lightsail"
    production_lightsail_principal_arn  = "arn:aws:iam::111111111111:role/fixture-production-lightsail"
  }

  assert {
    condition = length(aws_ssm_parameter.configuration) == 12 && alltrue([
      for environment in ["development", "production"] :
      aws_ssm_parameter.configuration["${environment}/iam/runtime-role-arn"].name == "/pawlocal/${environment}/config/iam/runtime-role-arn"
    ])
    error_message = "Runtime handoff must publish exactly one matching runtime-role key per actual managed role."
  }
}
