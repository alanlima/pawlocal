mock_provider "random" {}
mock_provider "time" {}
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
  environment                = "development"
  aws_region                 = "ap-southeast-2"
  root_domain                = "example.test"
  route53_zone_id            = "ZTEST"
  cloudfront_certificate_arn = "arn:aws:acm:us-east-1:111111111111:certificate/test"
  terraform_apply_role_name  = "pawlocal-development-terraform-apply"
  frontend_publish_role_name = "pawlocal-development-github-deploy"
  container_power            = "micro"
  cognito_password_policy = {
    minimum_length = 8, require_lowercase = false, require_uppercase = false, require_numbers = false
  }
}
run "receiver_is_default_disabled_without_credentials" {
  command = plan
  providers = {
    aws                    = aws.oncall_test
    aws.cognito_deployment = aws.oncall_test
    aws.oncall_deployment  = aws.oncall_test
  }
  assert {
    condition     = length(module.oncall_receiver) == 0 && length(aws_lambda_function_url.oncall_receiver) == 0 && length(aws_iam_role_policy.oncall_runtime) == 0 && output.oncall_receiver_url == null
    error_message = "Null configuration must create no receiver, URL or runtime grant."
  }
}
run "receiver_has_exact_runtime_sources_and_url_only_invoke" {
  command = plan
  providers = {
    aws                    = aws.oncall_test
    aws.cognito_deployment = aws.oncall_test
    aws.oncall_deployment  = aws.oncall_test
  }
  variables {
    oncall_receiver = {
      app_id           = "1", installation_id = "2", repository_id = "3", repository = "alanlima/pawlocal"
      allowed_services = ["pawlocal-api"], allowed_alerts = ["pawlocal-development-search-detail-failure"]
      kms_key_arn      = "arn:aws:kms:ap-southeast-2:111111111111:key/11111111-1111-1111-1111-111111111111"
    }
  }
  assert {
    condition = (
      !contains(keys(local.oncall_environment_variables), "PAWLOCAL_ONCALL_ALLOWED_ALERTS") &&
      jsondecode(local.oncall_environment_variables.PAWLOCAL_ONCALL_ALLOWED_SERVICES) == ["pawlocal-api"]
    )
    error_message = "Receiver environment must omit the alert-name filter even with populated compatibility allowed_alerts, while preserving service validation."
  }
  assert {
    condition     = module.oncall_receiver[0].lambda_function_name == "pawlocal-development-oncall-receiver" && aws_iam_role_policy.oncall_runtime[0].role == "pawlocal-development-oncall-receiver"
    error_message = "Environment owns resources and policy only on its fixed bootstrap-owned role."
  }
  assert {
    condition     = aws_ssm_parameter.oncall_webhook_url[0].tags["configuration-access"] == "github-public"
    error_message = "Only the public webhook URL producer must opt into the configuration reader's public tag contract."
  }
  assert {
    condition = (
      aws_lambda_function_url.oncall_receiver[0].authorization_type == "NONE" &&
      aws_lambda_permission.oncall_url[0].action == "lambda:InvokeFunctionUrl" &&
      aws_lambda_permission.oncall_url[0].function_url_auth_type == "NONE" &&
      aws_lambda_permission.oncall_via_url[0].action == "lambda:InvokeFunction" &&
      aws_lambda_permission.oncall_via_url[0].invoked_via_function_url
    )
    error_message = "Public grants must require Function URL invocation, never a general public InvokeFunction grant."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.oncall_runtime[0].policy).Statement[1].Resource == local.oncall_secret_arns &&
      length(local.oncall_secret_arns) == 2 &&
      jsondecode(aws_iam_role_policy.oncall_runtime[0].policy).Statement[2].Resource == [var.oncall_receiver.kms_key_arn] &&
      jsondecode(aws_iam_role_policy.oncall_runtime[0].policy).Statement[2].Condition.StringEquals["kms:EncryptionContext:PARAMETER_ARN"] == local.oncall_secret_arns
    )
    error_message = "SSM/KMS grants must name only the matching HMAC and dispatch key with exact encryption context."
  }
}
run "default_ssm_mode_adds_no_wildcard_kms_permission" {
  command = plan
  providers = {
    aws                    = aws.oncall_test
    aws.cognito_deployment = aws.oncall_test
    aws.oncall_deployment  = aws.oncall_test
  }
  variables {
    oncall_receiver = {
      app_id           = "1", installation_id = "2", repository_id = "3", repository = "alanlima/pawlocal"
      allowed_services = ["pawlocal-api"], allowed_alerts = ["pawlocal-development-search-detail-failure"]
    }
  }
  assert {
    condition     = length(jsondecode(aws_iam_role_policy.oncall_runtime[0].policy).Statement) == 2
    error_message = "Default aws/ssm mode must not invent a wildcard KMS grant or require a new customer key."
  }
}
run "reject_cross_account_or_environment_key" {
  command = plan
  providers = {
    aws                    = aws.oncall_test
    aws.cognito_deployment = aws.oncall_test
    aws.oncall_deployment  = aws.oncall_test
  }
  variables {
    oncall_receiver = {
      app_id           = "1", installation_id = "2", repository_id = "3", repository = "alanlima/pawlocal"
      allowed_services = ["pawlocal-api"], allowed_alerts = ["pawlocal-development-search-detail-failure"]
      kms_key_arn      = "arn:aws:kms:ap-southeast-2:222222222222:key/11111111-1111-1111-1111-111111111111"
    }
  }
  expect_failures = [var.oncall_receiver]
}
run "reject_unsafe_repository_number" {
  command = plan
  providers = {
    aws                    = aws.oncall_test
    aws.cognito_deployment = aws.oncall_test
    aws.oncall_deployment  = aws.oncall_test
  }
  variables {
    oncall_receiver = {
      app_id           = "1", installation_id = "2", repository_id = "9007199254740993", repository = "alanlima/pawlocal"
      allowed_services = ["pawlocal-api"], allowed_alerts = ["pawlocal-development-search-detail-failure"]
    }
  }
  expect_failures = [var.oncall_receiver]
}

run "nondefault_project_uses_matching_receiver_role_and_parameter_names" {
  command = plan
  providers = {
    aws                    = aws.oncall_test
    aws.cognito_deployment = aws.oncall_test
    aws.oncall_deployment  = aws.oncall_test
  }
  variables {
    project_name = "petdemo"
    oncall_receiver = {
      app_id           = "1", installation_id = "2", repository_id = "3", repository = "example/review-demo"
      allowed_services = ["pawlocal-api"], allowed_alerts = ["pawlocal-development-search-detail-failure"]
    }
  }
  assert {
    condition     = module.oncall_receiver[0].lambda_function_name == "petdemo-development-oncall-receiver" && aws_iam_role_policy.oncall_runtime[0].role == "petdemo-development-oncall-receiver" && aws_iam_role_policy.oncall_runtime[0].name == "petdemo-development-oncall-runtime" && aws_ssm_parameter.oncall_webhook_url[0].name == "/petdemo/development/config/oncall/webhook-url"
    error_message = "All receiver resource and public parameter names must use project_name."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.oncall_runtime[0].policy).Statement[1].Resource == ["arn:aws:ssm:ap-southeast-2:111111111111:parameter/petdemo/development/secrets/grafana/webhook-hmac", "arn:aws:ssm:ap-southeast-2:111111111111:parameter/petdemo/development/secrets/oncall/dispatch-app-private-key"]
    error_message = "Receiver policy secret prefixes must match its runtime project."
  }
}
