override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "111111111111"
  }
}

override_data {
  target = data.aws_partition.current
  values = {
    partition = "aws"
  }
}

provider "aws" {
  alias                       = "test"
  region                      = "ap-southeast-2"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

run "delegated_cognito_roles_are_exact_and_environment_isolated" {
  command = plan

  providers = {
    aws = aws.test
  }

  variables {
    # These lengths match the reviewed production-shaped bootstrap inputs so
    # short placeholders cannot hide policy-size or rendered-ARN regressions.
    terraform_state_bucket_name = "fixture-state-bucket-x"
    github_repository           = "example/pawlocal"
    github_owner_id             = "1"
    github_repository_id        = "2"
    manage_github_oidc_provider = true
    route53_zone_id             = "ZFIXTURE000000"
    domain_name                 = "fixture.example"
  }

  assert {
    condition = toset(keys(local.cognito_terraform_role_definitions)) == toset([
      "development-plan",
      "development-apply",
      "production-plan",
      "production-apply"
    ])
    error_message = "Only the two delegated Cognito Terraform roles per approved environment may be defined."
  }

  assert {
    condition = alltrue([
      for key, definition in local.cognito_terraform_role_definitions :
      aws_iam_role.cognito_terraform[key].name == "pawlocal-${definition.environment}-cognito-terraform-${definition.purpose}" &&
      aws_iam_role.cognito_terraform[key].max_session_duration == 3600 &&
      aws_iam_role.cognito_terraform[key].tags.environment == definition.environment &&
      aws_iam_role.cognito_terraform[key].tags.project == "pawlocal"
    ])
    error_message = "Delegated role names, one-hour sessions, and environment tags must stay deterministic."
  }

  assert {
    condition = alltrue([
      for key, trust in data.aws_iam_policy_document.cognito_terraform_trust :
      length(jsondecode(trust.minified_json).Statement) == 1 &&
      toset(flatten([jsondecode(trust.minified_json).Statement[0].Action])) == toset(["sts:AssumeRole"]) &&
      toset(flatten([jsondecode(trust.minified_json).Statement[0].Principal.AWS])) == toset([
        "arn:aws:iam::111111111111:role/pawlocal-${local.cognito_terraform_role_definitions[key].environment}-terraform-${local.cognito_terraform_role_definitions[key].purpose}"
      ]) &&
      !strcontains(trust.minified_json, "token.actions.githubusercontent.com") &&
      !strcontains(trust.minified_json, "AssumeRoleWithWebIdentity")
    ])
    error_message = "Each delegated role must trust only its exact matching existing Terraform role through sts:AssumeRole."
  }

  assert {
    condition = alltrue([
      for environment, names in local.cognito_resource_names :
      names.function == "pawlocal-${environment}-cognito-pre-signup" &&
      names.log_group == "/aws/lambda/pawlocal-${environment}-cognito-pre-signup" &&
      names.execution_role == "pawlocal-${environment}-cognito-pre-signup"
    ])
    error_message = "Lambda, log-group, and execution-role names must be deterministic per environment."
  }

  assert {
    condition = toset(local.cognito_lambda_read_actions) == toset([
      "lambda:GetFunction",
      "lambda:GetFunctionCodeSigningConfig",
      "lambda:GetPolicy",
      "lambda:ListTags",
      "lambda:ListVersionsByFunction"
    ])
    error_message = "Lambda refresh permissions must retain the complete provider 6.69.1 read call set."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_plan_permissions :
      toset(flatten([
        for statement in jsondecode(policy.minified_json).Statement : flatten([statement.Action])
        ])) == toset(concat(local.cognito_lambda_read_actions, [
        "logs:DescribeLogGroups",
        "logs:ListTagsForResource"
      ])) &&
      !strcontains(policy.minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Delegated plan policies must contain only the provider's exact matching read actions."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      toset(flatten([
        for statement in jsondecode(policy.minified_json).Statement : flatten([statement.Action])
        ])) == toset(concat(
        local.cognito_lambda_read_actions,
        local.cognito_lambda_mutation_actions,
        local.cognito_logs_mutation_actions,
        [
          "iam:PassRole",
          "lambda:CreateFunction",
          "lambda:TagResource",
          "lambda:UntagResource",
          "logs:CreateLogGroup",
          "logs:DescribeLogGroups",
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource"
        ]
      )) &&
      !strcontains(policy.minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Delegated apply policies must contain only the enumerated Lambda, Logs, and exact PassRole lifecycle."
  }

  assert {
    condition = alltrue(flatten([
      for policies in [
        data.aws_iam_policy_document.cognito_plan_permissions,
        data.aws_iam_policy_document.cognito_apply_permissions
        ] : [
        for environment, policy in policies :
        length([
          for statement in jsondecode(policy.minified_json).Statement : statement
          if contains(flatten([statement.Action]), "lambda:ListVersionsByFunction") &&
          toset(flatten([statement.Resource])) == toset([local.cognito_resource_arns[environment].function])
        ]) == 1
      ]
    ]))
    error_message = "Both delegated policies must authorize ListVersionsByFunction on only the exact matching function ARN."
  }

  assert {
    condition = alltrue(flatten([
      for policies in [
        data.aws_iam_policy_document.cognito_plan_permissions,
        data.aws_iam_policy_document.cognito_apply_permissions
        ] : [
        for environment, policy in policies :
        length([
          for statement in jsondecode(policy.minified_json).Statement : statement
          if toset(flatten([statement.Action])) == toset(["logs:DescribeLogGroups"]) &&
          toset(flatten([statement.Resource])) == toset(["*"]) &&
          statement.Condition.StringEquals["aws:RequestedRegion"] == "ap-southeast-2"
        ]) == 1
      ]
    ]))
    error_message = "Every delegated identity policy must have exactly one regional DescribeLogGroups-only wildcard statement."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      jsondecode(aws_iam_policy.cognito_apply_boundary[environment].policy) == jsondecode(policy.json) &&
      length(policy.minified_json) < local.iam_managed_policy_max_bytes
    ])
    error_message = "Each delegated apply boundary must exactly match the apply identity policy and stay below 6,144 bytes."
  }

  assert {
    condition = alltrue(flatten([
      for policies in [
        data.aws_iam_policy_document.cognito_plan_permissions,
        data.aws_iam_policy_document.cognito_apply_permissions
        ] : [
        for environment, policy in policies : alltrue([
          for statement in jsondecode(policy.minified_json).Statement :
          !contains(flatten([statement.Resource]), "*") || (
            toset(flatten([statement.Action])) == toset(["logs:DescribeLogGroups"]) &&
            statement.Condition.StringEquals["aws:RequestedRegion"] == "ap-southeast-2"
          )
        ])
      ]
    ]))
    error_message = "No delegated policy may use a wildcard resource except the approved regional DescribeLogGroups statement."
  }

  assert {
    condition = alltrue(flatten([
      for policies in [
        data.aws_iam_policy_document.cognito_plan_permissions,
        data.aws_iam_policy_document.cognito_apply_permissions
        ] : [
        for environment, policy in policies : alltrue([
          for statement in jsondecode(policy.minified_json).Statement :
          toset(flatten([statement.Resource])) == toset([local.cognito_resource_arns[environment].function])
          if length([for action in flatten([statement.Action]) : action if startswith(action, "lambda:")]) > 0
        ])
      ]
    ]))
    error_message = "Every Lambda read and mutation must use only the exact matching function ARN."
  }

  assert {
    condition = alltrue(flatten([
      for policies in [
        data.aws_iam_policy_document.cognito_plan_permissions,
        data.aws_iam_policy_document.cognito_apply_permissions
        ] : [
        for environment, policy in policies : alltrue([
          for statement in jsondecode(policy.minified_json).Statement :
          toset(flatten([statement.Resource])) == toset([
            contains(flatten([statement.Action]), "logs:ListTagsForResource") ||
            contains(flatten([statement.Action]), "logs:TagResource") ||
            contains(flatten([statement.Action]), "logs:UntagResource")
            ? local.cognito_resource_arns[environment].log_group_tags
            : local.cognito_resource_arns[environment].log_group
          ])
          if length([for action in flatten([statement.Action]) : action if startswith(action, "logs:") && action != "logs:DescribeLogGroups"]) > 0
        ])
      ]
    ]))
    error_message = "Logs actions must use the exact matching ARN form, including the no-suffix ARN required for tagging APIs."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if toset(flatten([statement.Action])) == toset(["iam:PassRole"]) &&
        toset(flatten([statement.Resource])) == toset([local.cognito_resource_arns[environment].execution_role]) &&
        statement.Condition.StringEquals["iam:PassedToService"] == "lambda.amazonaws.com"
      ]) == 1
    ])
    error_message = "PassRole must target only the exact matching execution role and only Lambda."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      length(setintersection(
        toset(flatten([for statement in jsondecode(policy.minified_json).Statement : flatten([statement.Action])])),
        toset([
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:GetLogRecord",
          "logs:GetLogGroupFields",
          "logs:StartQuery",
          "logs:GetQueryResults",
          "logs:StartLiveTail",
          "logs:Unmask"
        ])
      )) == 0 &&
      !strcontains(policy.minified_json, "logs:Describe*") &&
      !strcontains(policy.minified_json, "logs:*") &&
      !strcontains(policy.minified_json, "cognito-idp:") &&
      !strcontains(policy.minified_json, "s3:")
    ])
    error_message = "Delegated roles must not read log content or access Cognito, Terraform state, or saved-plan storage."
  }

  assert {
    condition = alltrue([
      for key, definition in local.cognito_terraform_role_definitions :
      length([
        for statement in jsondecode(data.aws_iam_policy_document.role_permissions[key].minified_json).Statement : statement
        if statement.Sid == "AssumeOnlyMatchingCognitoTerraformRole" &&
        toset(flatten([statement.Action])) == toset(["sts:AssumeRole"]) &&
        toset(flatten([statement.Resource])) == toset([
          "arn:aws:iam::111111111111:role/pawlocal-${definition.environment}-cognito-terraform-${definition.purpose}"
        ])
      ]) == 1 &&
      length([
        for action in flatten([
          for statement in jsondecode(data.aws_iam_policy_document.role_permissions[key].minified_json).Statement : flatten([statement.Action])
        ]) : action
        if startswith(action, "lambda:") || startswith(action, "logs:") || action == "iam:PassRole"
      ]) == 0
    ])
    error_message = "Existing environment identities may gain only exact matching AssumeRole, never direct Lambda, Logs, or PassRole authority."
  }

  assert {
    condition = alltrue([
      for environment, trust in data.aws_iam_policy_document.cognito_pre_sign_up_trust :
      length(jsondecode(trust.minified_json).Statement) == 1 &&
      toset(flatten([jsondecode(trust.minified_json).Statement[0].Action])) == toset(["sts:AssumeRole"]) &&
      toset(flatten([jsondecode(trust.minified_json).Statement[0].Principal.Service])) == toset(["lambda.amazonaws.com"])
    ])
    error_message = "Each execution role must trust only the Lambda service."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_pre_sign_up_permissions :
      length(jsondecode(policy.minified_json).Statement) == 1 &&
      toset(flatten([jsondecode(policy.minified_json).Statement[0].Action])) == toset([
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]) &&
      toset(flatten([jsondecode(policy.minified_json).Statement[0].Resource])) == toset([
        local.cognito_resource_arns[environment].log_stream
      ])
    ])
    error_message = "Each execution role may write only matching pre-sign-up log streams."
  }

  assert {
    condition = (
      toset(keys(output.cognito_terraform_role_arns)) == toset(["development", "production"]) &&
      alltrue([
        for environment in keys(local.environments) :
        toset(keys(output.cognito_terraform_role_arns[environment])) == toset(["plan", "apply"])
      ]) &&
      toset(keys(output.cognito_pre_sign_up_role_arns)) == toset(["development", "production"])
    )
    error_message = "Cognito role outputs must retain the approved environment and plan/apply key structure."
  }
}
