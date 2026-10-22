mock_provider "random" {}
mock_provider "time" {}

provider "aws" {
  alias                       = "test"
  region                      = "ap-southeast-2"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

provider "aws" {
  alias                       = "cognito_test"
  region                      = "ap-southeast-2"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

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

override_resource {
  target          = aws_lambda_function.cognito_pre_sign_up
  override_during = plan
  values = {
    arn           = "arn:aws:lambda:ap-southeast-2:111111111111:function:pawlocal-development-cognito-pre-signup"
    function_name = "pawlocal-development-cognito-pre-signup"
  }
}

override_resource {
  target          = aws_cognito_user_pool.application
  override_during = plan
  values = {
    arn = "arn:aws:cognito-idp:ap-southeast-2:111111111111:userpool/ap-southeast-2_TEST"
  }
}

run "development_uses_relaxed_password_policy_and_default_role" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                = "development"
    aws_region                 = "ap-southeast-2"
    root_domain                = "example.test"
    route53_zone_id            = "ZTEST"
    cloudfront_certificate_arn = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    cognito_password_policy = {
      minimum_length    = 8
      require_lowercase = false
      require_uppercase = false
      require_numbers   = false
    }
    terraform_apply_role_name  = "pawlocal-development-terraform-apply"
    frontend_publish_role_name = "pawlocal-development-github-deploy"
    container_power            = "micro"
  }

  assert {
    condition = (
      aws_cognito_user_pool.application.password_policy[0].minimum_length == 8 &&
      !aws_cognito_user_pool.application.password_policy[0].require_lowercase &&
      !aws_cognito_user_pool.application.password_policy[0].require_uppercase &&
      !aws_cognito_user_pool.application.password_policy[0].require_numbers &&
      !aws_cognito_user_pool.application.password_policy[0].require_symbols &&
      aws_cognito_user_pool.application.password_policy[0].temporary_password_validity_days == 7
    )
    error_message = "Development must use the exact relaxed password policy with symbols disabled."
  }

  assert {
    condition = (
      !aws_cognito_user_pool.application.admin_create_user_config[0].allow_admin_create_user_only &&
      aws_cognito_user_pool.application.mfa_configuration == "OFF" &&
      !aws_cognito_user_pool.application.username_configuration[0].case_sensitive &&
      try(length(aws_cognito_user_pool.application.username_attributes), 0) == 0 &&
      try(length(aws_cognito_user_pool.application.alias_attributes), 0) == 0 &&
      try(length(aws_cognito_user_pool.application.auto_verified_attributes), 0) == 0
    )
    error_message = "The pool must use open username-only sign-up, case-insensitive usernames, no auto-verification, and MFA off."
  }

  assert {
    condition = (
      length([for attribute in aws_cognito_user_pool.application.schema : attribute if attribute.name == "name"]) == 1 &&
      one([for attribute in aws_cognito_user_pool.application.schema : attribute if attribute.name == "name"]).attribute_data_type == "String" &&
      one([for attribute in aws_cognito_user_pool.application.schema : attribute if attribute.name == "name"]).mutable &&
      one([for attribute in aws_cognito_user_pool.application.schema : attribute if attribute.name == "name"]).required
    )
    error_message = "The standard name attribute must be required and mutable."
  }

  assert {
    condition = (
      local.default_cognito_pre_sign_up_role_arn == "arn:aws:iam::111111111111:role/pawlocal-development-cognito-pre-signup" &&
      local.cognito_pre_sign_up_role_arn == local.default_cognito_pre_sign_up_role_arn &&
      data.archive_file.cognito_pre_sign_up.source_file == "${path.module}/lambda/cognito-pre-signup/index.mjs" &&
      data.archive_file.cognito_pre_sign_up.output_file_mode == "0666" &&
      data.archive_file.cognito_pre_sign_up.output_path == "${path.root}/.terraform/pawlocal-development-cognito-pre-signup.zip" &&
      aws_lambda_function.cognito_pre_sign_up.role == local.default_cognito_pre_sign_up_role_arn &&
      aws_cloudwatch_log_group.cognito_pre_sign_up.name == "/aws/lambda/pawlocal-development-cognito-pre-signup" &&
      aws_cloudwatch_log_group.cognito_pre_sign_up.retention_in_days == 30 &&
      aws_lambda_function.cognito_pre_sign_up.function_name == "pawlocal-development-cognito-pre-signup" &&
      aws_lambda_function.cognito_pre_sign_up.handler == "index.handler" &&
      aws_lambda_function.cognito_pre_sign_up.runtime == "nodejs22.x"
    )
    error_message = "The default execution role, function, and finite-retention log group must be deterministic and environment-specific."
  }

  assert {
    condition = (
      aws_cognito_user_pool.application.lambda_config[0].pre_sign_up == aws_lambda_function.cognito_pre_sign_up.arn &&
      aws_lambda_permission.allow_cognito_pre_sign_up.action == "lambda:InvokeFunction" &&
      aws_lambda_permission.allow_cognito_pre_sign_up.function_name == aws_lambda_function.cognito_pre_sign_up.function_name &&
      aws_lambda_permission.allow_cognito_pre_sign_up.principal == "cognito-idp.amazonaws.com" &&
      aws_lambda_permission.allow_cognito_pre_sign_up.source_arn == aws_cognito_user_pool.application.arn &&
      aws_lambda_permission.allow_cognito_pre_sign_up.source_account == "111111111111"
    )
    error_message = "Cognito invoke permission must be scoped to the matching function, pool, service principal, and account."
  }
}

run "production_uses_strict_password_policy_and_exact_override" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                  = "production"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::111111111111:role/pawlocal-production-cognito-pre-signup"
    terraform_apply_role_name    = "pawlocal-production-terraform-apply"
    frontend_publish_role_name   = "pawlocal-production-github-deploy"
    container_power              = "medium"
    cognito_password_policy = {
      minimum_length    = 12
      require_lowercase = true
      require_uppercase = true
      require_numbers   = true
    }
  }

  assert {
    condition = (
      aws_cognito_user_pool.application.password_policy[0].minimum_length == 12 &&
      aws_cognito_user_pool.application.password_policy[0].require_lowercase &&
      aws_cognito_user_pool.application.password_policy[0].require_uppercase &&
      aws_cognito_user_pool.application.password_policy[0].require_numbers &&
      !aws_cognito_user_pool.application.password_policy[0].require_symbols &&
      !aws_cognito_user_pool.application.admin_create_user_config[0].allow_admin_create_user_only &&
      aws_cognito_user_pool.application.mfa_configuration == "OFF" &&
      !aws_cognito_user_pool.application.username_configuration[0].case_sensitive &&
      try(length(aws_cognito_user_pool.application.username_attributes), 0) == 0 &&
      try(length(aws_cognito_user_pool.application.alias_attributes), 0) == 0 &&
      try(length(aws_cognito_user_pool.application.auto_verified_attributes), 0) == 0
    )
    error_message = "Production must use the exact strict policy while preserving every common pool setting."
  }

  assert {
    condition = (
      local.cognito_pre_sign_up_role_arn == local.default_cognito_pre_sign_up_role_arn &&
      aws_lambda_function.cognito_pre_sign_up.role == local.default_cognito_pre_sign_up_role_arn
    )
    error_message = "The exact approved override must retain the same sole execution-role identity as the default path."
  }
}

run "password_minimum_below_cognito_range_is_rejected" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                = "development"
    aws_region                 = "ap-southeast-2"
    root_domain                = "example.test"
    route53_zone_id            = "ZTEST"
    cloudfront_certificate_arn = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    terraform_apply_role_name  = "pawlocal-development-terraform-apply"
    frontend_publish_role_name = "pawlocal-development-github-deploy"
    container_power            = "micro"
    cognito_password_policy = {
      minimum_length    = 5
      require_lowercase = false
      require_uppercase = false
      require_numbers   = false
    }
  }

  expect_failures = [var.cognito_password_policy]
}

run "password_minimum_above_cognito_range_is_rejected" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                = "production"
    aws_region                 = "ap-southeast-2"
    root_domain                = "example.test"
    route53_zone_id            = "ZTEST"
    cloudfront_certificate_arn = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    terraform_apply_role_name  = "pawlocal-production-terraform-apply"
    frontend_publish_role_name = "pawlocal-production-github-deploy"
    container_power            = "medium"
    cognito_password_policy = {
      minimum_length    = 100
      require_lowercase = true
      require_uppercase = true
      require_numbers   = true
    }
  }

  expect_failures = [var.cognito_password_policy]
}

run "wrong_account_override_is_rejected" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                  = "development"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::222222222222:role/pawlocal-development-cognito-pre-signup"
    terraform_apply_role_name    = "pawlocal-development-terraform-apply"
    frontend_publish_role_name   = "pawlocal-development-github-deploy"
    container_power              = "micro"
    cognito_password_policy = {
      minimum_length    = 8
      require_lowercase = false
      require_uppercase = false
      require_numbers   = false
    }
  }

  expect_failures = [aws_lambda_function.cognito_pre_sign_up]
}

run "wrong_partition_override_is_rejected" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                  = "production"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    cognito_pre_sign_up_role_arn = "arn:aws-us-gov:iam::111111111111:role/pawlocal-production-cognito-pre-signup"
    terraform_apply_role_name    = "pawlocal-production-terraform-apply"
    frontend_publish_role_name   = "pawlocal-production-github-deploy"
    container_power              = "medium"
    cognito_password_policy = {
      minimum_length    = 12
      require_lowercase = true
      require_uppercase = true
      require_numbers   = true
    }
  }

  expect_failures = [aws_lambda_function.cognito_pre_sign_up]
}

run "wrong_environment_override_is_rejected" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                  = "development"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::111111111111:role/pawlocal-production-cognito-pre-signup"
    terraform_apply_role_name    = "pawlocal-development-terraform-apply"
    frontend_publish_role_name   = "pawlocal-development-github-deploy"
    container_power              = "micro"
    cognito_password_policy = {
      minimum_length    = 8
      require_lowercase = false
      require_uppercase = false
      require_numbers   = false
    }
  }

  expect_failures = [aws_lambda_function.cognito_pre_sign_up]
}

run "wrong_role_name_override_is_rejected" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                  = "development"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::111111111111:role/pawlocal-development-other"
    terraform_apply_role_name    = "pawlocal-development-terraform-apply"
    frontend_publish_role_name   = "pawlocal-development-github-deploy"
    container_power              = "micro"
    cognito_password_policy = {
      minimum_length    = 8
      require_lowercase = false
      require_uppercase = false
      require_numbers   = false
    }
  }

  expect_failures = [var.cognito_pre_sign_up_role_arn]
}
