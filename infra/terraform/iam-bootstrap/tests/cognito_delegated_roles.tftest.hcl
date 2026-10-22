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

  default_tags {
    tags = {
      project   = "pawhub"
      managedby = "terraform"
    }
  }
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
    project_name                = "pawhub"
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
      aws_iam_role.cognito_terraform[key].tags.purpose == "cognito-terraform-${definition.purpose}" &&
      toset(keys(aws_iam_role.cognito_terraform[key].tags)) == toset(["environment", "purpose"]) &&
      aws_iam_role.cognito_terraform[key].tags_all.project == "pawhub" &&
      aws_iam_role.cognito_terraform[key].tags_all.managedby == "terraform"
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
    condition = (
      local.cognito_common_tags == {
        project    = "pawhub"
        managedby  = "terraform"
        component  = "fullstack-mvp"
        workload   = "application"
        costcenter = "personal"
      } &&
      alltrue([
        for environment, tags in local.cognito_application_tags :
        tags == merge(local.cognito_common_tags, { environment = environment }) &&
        toset(keys(tags)) == toset(concat(keys(local.cognito_common_tags), ["environment"])) &&
        tags.environment == environment
      ])
    )
    error_message = "Each Cognito application tag map must contain only the common tags plus its matching environment."
  }

  assert {
    condition = alltrue([
      for environment in keys(local.environments) :
      aws_iam_policy.cognito_apply_boundary[environment].tags.environment == environment &&
      aws_iam_policy.cognito_apply_boundary[environment].tags.purpose == "cognito-terraform-apply-boundary" &&
      toset(keys(aws_iam_policy.cognito_apply_boundary[environment].tags)) == toset(["environment", "purpose"]) &&
      aws_iam_role.cognito_pre_sign_up[environment].tags.environment == environment &&
      aws_iam_role.cognito_pre_sign_up[environment].tags.purpose == "cognito-pre-signup" &&
      toset(keys(aws_iam_role.cognito_pre_sign_up[environment].tags)) == toset(["environment", "purpose"]) &&
      aws_iam_policy.cognito_apply_boundary[environment].tags_all.project == "pawhub" &&
      aws_iam_policy.cognito_apply_boundary[environment].tags_all.managedby == "terraform" &&
      aws_iam_role.cognito_pre_sign_up[environment].tags_all.project == "pawhub" &&
      aws_iam_role.cognito_pre_sign_up[environment].tags_all.managedby == "terraform"
    ])
    error_message = "Provider defaults must supply shared tags while Cognito IAM resources declare only environment and purpose additions."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      toset(flatten([
        for statement in jsondecode(policy.minified_json).Statement : [
          for operator, conditions in try(statement.Condition, {}) : [
            for variable, values in conditions : flatten([values])
            if contains(["aws:RequestTag/project", "aws:ResourceTag/project"], variable)
          ]
        ]
      ])) == toset(["pawhub"])
    ])
    error_message = "A non-default project_name must propagate to every request-tag and resource-tag project condition."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if statement.Sid == "CreateLambda" &&
        toset(flatten([statement.Action])) == toset(["lambda:CreateFunction", "lambda:TagResource"]) &&
        toset(flatten([statement.Resource])) == toset([local.cognito_resource_arns[environment].function]) &&
        statement.Condition.StringEquals["aws:RequestTag/project"] == "pawhub" &&
        statement.Condition.StringEquals["aws:RequestTag/environment"] == environment &&
        statement.Condition.StringEquals["aws:ResourceTag/project"] == "pawhub" &&
        statement.Condition.StringEquals["aws:ResourceTag/environment"] == environment
      ]) == 1
    ])
    error_message = "Lambda create-time TagResource must require matching request and surfaced resource ownership tags on only the exact function ARN."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if statement.Sid == "TagNewLogGroup" &&
        toset(flatten([statement.Action])) == toset(["logs:TagResource"]) &&
        toset(flatten([statement.Resource])) == toset([
          local.cognito_resource_arns[environment].log_group_tags,
          local.cognito_resource_arns[environment].log_group
        ]) &&
        toset(keys(statement.Condition)) == toset(["StringEquals", "ForAllValues:StringEquals"]) &&
        statement.Condition.StringEquals == {
          for key, value in local.cognito_application_tags[environment] : "aws:RequestTag/${key}" => value
        } &&
        toset(statement.Condition["ForAllValues:StringEquals"]["aws:TagKeys"]) == toset(keys(local.cognito_application_tags[environment])) &&
        !anytrue(flatten([
          for operator, conditions in statement.Condition : [
            for key in keys(conditions) : startswith(key, "aws:ResourceTag/")
          ]
        ]))
        ]) == 1 && alltrue([
        for statement in jsondecode(policy.minified_json).Statement :
        statement.Condition.StringEquals["aws:ResourceTag/project"] == "pawhub" &&
        statement.Condition.StringEquals["aws:ResourceTag/environment"] == environment
        if statement.Sid != "TagNewLogGroup" && (
          contains(flatten([statement.Action]), "lambda:TagResource") ||
          contains(flatten([statement.Action]), "logs:TagResource")
        )
      ])
    ])
    error_message = "Logs creation must admit absent ownership tags; other tag grants must retain matching ownership tags."
  }

  # Evaluate the rendered create + dependent-tag statements with no existing
  # ResourceTags. Each request must pass BOTH identity and boundary checks.
  assert {
    condition = alltrue(flatten([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions : [
        for document in [
          jsondecode(aws_iam_role_policy.cognito_terraform["${environment}-apply"].policy),
          jsondecode(aws_iam_policy.cognito_apply_boundary[environment].policy)
          ] : [for request in [
            { tags = local.cognito_application_tags[environment], target = environment, name_suffix = "", allowed = true },
            { tags = {}, target = environment, name_suffix = "", allowed = false },
            { tags = { for key, value in local.cognito_application_tags[environment] : key => value if key != "managedby" }, target = environment, name_suffix = "", allowed = false },
            { tags = merge(local.cognito_application_tags[environment], { environment = "wrong" }), target = environment, name_suffix = "", allowed = false },
            { tags = merge(local.cognito_application_tags[environment], { project = "wrong" }), target = environment, name_suffix = "", allowed = false },
            { tags = merge(local.cognito_application_tags[environment], { unexpected = "tag" }), target = environment, name_suffix = "", allowed = false },
            { tags = local.cognito_application_tags[environment], target = environment == "development" ? "production" : "development", name_suffix = "", allowed = false },
            { tags = local.cognito_application_tags[environment], target = environment, name_suffix = "-other", allowed = false }
            ] : [for tag_arn_suffix in ["", ":*"] : alltrue([
              for operation in [
                { action = "logs:CreateLogGroup", resource = "${local.cognito_resource_arns[request.target].log_group_tags}${request.name_suffix}:*" },
                { action = "logs:TagResource", resource = "${local.cognito_resource_arns[request.target].log_group_tags}${request.name_suffix}${tag_arn_suffix}" }
                ] : anytrue([
                  for statement in document.Statement : try(
                    statement.Effect == "Allow" &&
                    contains(flatten([statement.Action]), operation.action) &&
                    anytrue([for pattern in flatten([statement.Resource]) :
                      can(regex("^${replace(replace(pattern, ".", "\\."), "*", ".*")}$", operation.resource))
                    ]) &&
                    alltrue([for key, value in statement.Condition.StringEquals :
                      lookup({ for tag, tag_value in request.tags : "aws:RequestTag/${tag}" => tag_value }, key, "") == value
                    ]) &&
                    alltrue([for key in keys(request.tags) : contains(statement.Condition["ForAllValues:StringEquals"]["aws:TagKeys"], key)]),
                    false
                  )
              ])
        ]) == request.allowed]]
      ]
    ]))
    error_message = "Create-with-tags must pass identity and boundary without ResourceTags; missing, wrong, extra, or cross-environment requests must fail."
  }

  # IAM's :* pattern also matches stream suffixes beneath this same group.
  # Do not confuse this with service authorization: Logs TagResource supports
  # log-group, not log-stream. No stream action is added by this statement.
  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      alltrue([for statement in jsondecode(policy.minified_json).Statement :
        anytrue([for pattern in flatten([statement.Resource]) :
          can(regex("^${replace(replace(pattern, ".", "\\."), "*", ".*")}$", "${local.cognito_resource_arns[environment].log_group_tags}:log-stream:fixture"))
        ]) && toset(flatten([statement.Action])) == toset(["logs:TagResource"])
        if statement.Sid == "TagNewLogGroup"
      ])
    ])
    error_message = "The exact-group suffix wildcard must be modeled honestly and grant only TagResource, not stream creation, writes, or reads."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.cognito_apply_permissions :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if statement.Sid == "GrantCognitoInvoke" &&
        toset(flatten([statement.Action])) == toset(["lambda:AddPermission"]) &&
        toset(flatten([statement.Resource])) == toset([local.cognito_resource_arns[environment].function]) &&
        statement.Condition.StringEquals["aws:ResourceTag/project"] == "pawhub" &&
        statement.Condition.StringEquals["aws:ResourceTag/environment"] == environment &&
        statement.Condition.StringEquals["lambda:Principal"] == "cognito-idp.amazonaws.com"
        ]) == 1 && length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "lambda:AddPermission") && statement.Sid != "GrantCognitoInvoke"
      ]) == 0
    ])
    error_message = "AddPermission must be isolated to the exact owned function and Cognito service principal."
  }

  assert {
    condition = (
      local.app_resource_tags["aws:ResourceTag/project"] == "pawhub" &&
      local.env_tag["aws:ResourceTag/project"] == "pawhub" &&
      alltrue([
        for tags in local.environment_dsql_tags : tags.project == "pawhub"
      ]) &&
      alltrue([
        for policy in data.aws_iam_policy_document.environment_apply_boundary :
        length(flatten([
          for statement in jsondecode(policy.minified_json).Statement : [
            for operator, conditions in try(statement.Condition, {}) : [
              for variable, values in conditions : flatten([values])
              if contains(["aws:RequestTag/project", "aws:ResourceTag/project"], variable)
            ]
          ]
          ])) == 11 && toset(flatten([
          for statement in jsondecode(policy.minified_json).Statement : [
            for operator, conditions in try(statement.Condition, {}) : [
              for variable, values in conditions : flatten([values])
              if contains(["aws:RequestTag/project", "aws:ResourceTag/project"], variable)
            ]
          ]
        ])) == toset(["pawhub"])
      ]) &&
      alltrue([
        for policy in data.aws_iam_policy_document.identity_app_role_boundary :
        length(flatten([
          for statement in jsondecode(policy.minified_json).Statement : [
            for operator, conditions in try(statement.Condition, {}) : [
              for variable, values in conditions : flatten([values])
              if contains(["aws:RequestTag/project", "aws:ResourceTag/project"], variable)
            ]
          ]
          ])) == 2 && toset(flatten([
          for statement in jsondecode(policy.minified_json).Statement : [
            for operator, conditions in try(statement.Condition, {}) : [
              for variable, values in conditions : flatten([values])
              if contains(["aws:RequestTag/project", "aws:ResourceTag/project"], variable)
            ]
          ]
        ])) == toset(["pawhub"])
      ])
    )
    error_message = "A non-default project_name must propagate through every bootstrap application project-tag local and policy condition."
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
          "lambda:AddPermission",
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
          toset(flatten([statement.Resource])) == (statement.Sid == "TagNewLogGroup" ? toset([
            local.cognito_resource_arns[environment].log_group_tags,
            local.cognito_resource_arns[environment].log_group
            ]) : toset([
            contains(flatten([statement.Action]), "logs:ListTagsForResource") ||
            contains(flatten([statement.Action]), "logs:TagResource") ||
            contains(flatten([statement.Action]), "logs:UntagResource")
            ? local.cognito_resource_arns[environment].log_group_tags
            : local.cognito_resource_arns[environment].log_group
          ]))
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

run "project_name_over_policy_budget_is_rejected" {
  command = plan

  providers = {
    aws = aws.test
  }

  variables {
    terraform_state_bucket_name = "fixture-state-bucket-x"
    github_repository           = "example/pawlocal"
    github_owner_id             = "1"
    github_repository_id        = "2"
    manage_github_oidc_provider = true
    project_name                = "pawlocalx"
    route53_zone_id             = "ZFIXTURE000000"
    domain_name                 = "fixture.example"
  }

  expect_failures = [var.project_name]
}

run "project_name_with_policy_escaping_is_rejected" {
  command = plan

  providers = {
    aws = aws.test
  }

  variables {
    terraform_state_bucket_name = "fixture-state-bucket-x"
    github_repository           = "example/pawlocal"
    github_owner_id             = "1"
    github_repository_id        = "2"
    manage_github_oidc_provider = true
    project_name                = "paw/loc"
    route53_zone_id             = "ZFIXTURE000000"
    domain_name                 = "fixture.example"
  }

  expect_failures = [var.project_name]
}
