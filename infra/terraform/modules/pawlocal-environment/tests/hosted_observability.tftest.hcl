mock_provider "random" {}
mock_provider "time" {}
mock_provider "grafana" {}

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
  values = { account_id = "111111111111" }
}

override_data {
  target = data.aws_partition.current
  values = { partition = "aws" }
}

override_data {
  target = data.grafana_cloud_stack.selected
  values = {
    id       = 12345
    url      = "https://fixture.grafana.net/"
    otlp_url = "https://otlp-gateway.grafana.net/otlp"
  }
}

override_resource {
  target          = random_id.cognito_domain_suffix
  override_during = plan
  values          = { hex = "c0ffee" }
}

override_resource {
  target          = aws_cognito_user_pool_client.browser
  override_during = plan
  values          = { id = "fixture-client" }
}

override_resource {
  target          = aws_dsql_cluster.application
  override_during = plan
  values          = { arn = "arn:aws:dsql:ap-southeast-2:111111111111:cluster/aaaaaaaaaaaaaaaaaaaaaaaaaa", identifier = "aaaaaaaaaaaaaaaaaaaaaaaaaa" }
}
override_resource {
  target          = aws_cognito_user_pool.application
  override_during = plan
  values          = { id = "ap-southeast-2_fixture", arn = "arn:aws:cognito-idp:ap-southeast-2:111111111111:userpool/ap-southeast-2_fixture" }
}

variables {
  environment                = "development"
  aws_region                 = "ap-southeast-2"
  root_domain                = "fixture.example"
  route53_zone_id            = "ZFIXTURE000000"
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
  runtime_role_arn           = "arn:aws:iam::111111111111:role/pawlocal-development-dsql-runtime"
  backend_image              = "ghcr.io/alanlima/pawlocal-api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}


run "disabled_hosted_mode_has_no_secret_read" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  assert {
    condition     = local.application_configuration_values["observability/enabled"] == "false" && !contains(keys(aws_ssm_parameter.configuration), "grafana/otlp-endpoint") && alltrue([for s in data.aws_iam_policy_document.runtime[0].statement : !contains(flatten([s.actions]), "ssm:GetParameter")]) && local.backend_runtime_environment["OTEL_SDK_DISABLED"] == "true"
    error_message = "Default disabled mode must publish false, deny ingestion secret reads and disable the deployed SDK."
  }
}

run "enabled_mode_exact_runtime_secret_and_public_bindings" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = true
      stack_url          = "https://fixture.grafana.net/"
      otlp_endpoint      = "https://otlp-gateway.grafana.net/otlp"
      otlp_instance_id   = "12345"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
      kms_key_arn        = "arn:aws:kms:ap-southeast-2:111111111111:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  }
  assert {
    condition     = local.application_configuration_values["observability/enabled"] == "true" && local.application_configuration_values["grafana/otlp-endpoint"] == var.hosted_observability.otlp_endpoint && alltrue([for p in values(aws_ssm_parameter.configuration) : p.type == "String" && p.tags["configuration-access"] == "github-public"])
    error_message = "Only actual public bindings must be published as tagged Strings."
  }
  assert {
    condition     = length(data.aws_iam_policy_document.runtime[0].statement) == 3 && one(one([for s in data.aws_iam_policy_document.runtime[0].statement : s if contains(flatten([s.actions]), "ssm:GetParameter")]).resources) == local.hosted_token_arn && one(one([for c in one([for s in data.aws_iam_policy_document.runtime[0].statement : s if contains(flatten([s.actions]), "kms:Decrypt")]).condition : c if c.variable == "kms:EncryptionContext:PARAMETER_ARN"]).values) == local.hosted_token_arn
    error_message = "Runtime may read only its exact OTLP secret, with exact matching KMS context when configured."
  }
  assert {
    condition     = local.backend_runtime_environment["OTEL_SDK_DISABLED"] == "false" && local.backend_runtime_environment["OTEL_EXPORTER_OTLP_ENDPOINT"] == var.hosted_observability.otlp_endpoint && !contains(keys(local.backend_runtime_environment), "OTEL_EXPORTER_OTLP_HEADERS")
    error_message = "Release runtime must match the enabled public mode without credential payload environment variables."
  }
}

run "private_endpoint_input_denied" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = true
      stack_url          = "https://fixture.grafana.net/"
      otlp_endpoint      = "https://private:credential@otlp.grafana.net/otlp"
      otlp_instance_id   = "12345"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
    }
  }
  expect_failures = [var.hosted_observability]
}

run "independent_backend_false_frontend_false" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = false
      frontend_enabled   = false
      stack_url          = "https://fixture.grafana.net/"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
    }
  }
  assert {
    condition     = local.application_configuration_values["observability/enabled"] == "false" && local.application_configuration_values["frontend/telemetry-enabled"] == "false" && local.backend_runtime_environment["PAWLOCAL_TELEMETRY_ENABLED"] == "false"
    error_message = "Backend runtime and independent public browser mode must match their own inputs."
  }
  assert {
    condition     = length([for s in data.aws_iam_policy_document.runtime[0].statement : s if contains(flatten([s.actions]), "ssm:GetParameter")]) == 0
    error_message = "Browser telemetry must not grant OTLP credential access."
  }
  assert {
    condition     = !contains(keys(aws_ssm_parameter.configuration), "grafana/otlp-endpoint") && !contains(keys(aws_ssm_parameter.configuration), "grafana/otlp-instance-id")
    error_message = "Backend-disabled browser-only bindings need no OTLP parameters."
  }
}

run "independent_backend_false_frontend_true" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = false
      frontend_enabled   = true
      stack_url          = "https://fixture.grafana.net/"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
    }
  }
  assert {
    condition     = local.application_configuration_values["observability/enabled"] == "false" && local.application_configuration_values["frontend/telemetry-enabled"] == "true" && local.backend_runtime_environment["PAWLOCAL_TELEMETRY_ENABLED"] == "false"
    error_message = "Backend runtime and independent public browser mode must match their own inputs."
  }
  assert {
    condition     = length([for s in data.aws_iam_policy_document.runtime[0].statement : s if contains(flatten([s.actions]), "ssm:GetParameter")]) == 0
    error_message = "Browser telemetry must not grant OTLP credential access."
  }
  assert {
    condition     = !contains(keys(aws_ssm_parameter.configuration), "grafana/otlp-endpoint") && !contains(keys(aws_ssm_parameter.configuration), "grafana/otlp-instance-id")
    error_message = "Backend-disabled browser-only bindings need no OTLP parameters."
  }
}

run "independent_backend_true_frontend_false" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = true
      frontend_enabled   = false
      stack_url          = "https://fixture.grafana.net/"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
      otlp_endpoint      = "https://gateway.grafana.net/otlp"
      otlp_instance_id   = "12345"
    }
  }
  assert {
    condition     = local.application_configuration_values["observability/enabled"] == "true" && local.application_configuration_values["frontend/telemetry-enabled"] == "false" && local.backend_runtime_environment["PAWLOCAL_TELEMETRY_ENABLED"] == "true"
    error_message = "Backend runtime and independent public browser mode must match their own inputs."
  }
  assert {
    condition     = length([for s in data.aws_iam_policy_document.runtime[0].statement : s if contains(flatten([s.actions]), "ssm:GetParameter")]) == 1
    error_message = "Browser telemetry must not grant OTLP credential access."
  }
  assert {
    condition     = one(aws_lightsail_container_service_deployment_version.api[0].container).environment["OTEL_EXPORTER_OTLP_ENDPOINT"] == local.hosted_otlp_endpoint && one(aws_lightsail_container_service_deployment_version.api[0].container).environment["PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID"] == local.hosted_otlp_instance_id
    error_message = "Enabled backend export must retain the configured endpoint and instance in the actual container."
  }

}

run "independent_backend_true_frontend_true" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = true
      frontend_enabled   = true
      stack_url          = "https://fixture.grafana.net/"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
      otlp_endpoint      = "https://gateway.grafana.net/otlp"
      otlp_instance_id   = "12345"
    }
  }
  assert {
    condition     = local.application_configuration_values["observability/enabled"] == "true" && local.application_configuration_values["frontend/telemetry-enabled"] == "true" && local.backend_runtime_environment["PAWLOCAL_TELEMETRY_ENABLED"] == "true"
    error_message = "Backend runtime and independent public browser mode must match their own inputs."
  }
  assert {
    condition     = length([for s in data.aws_iam_policy_document.runtime[0].statement : s if contains(flatten([s.actions]), "ssm:GetParameter")]) == 1
    error_message = "Browser telemetry must not grant OTLP credential access."
  }
  assert {
    condition     = one(aws_lightsail_container_service_deployment_version.api[0].container).environment["OTEL_EXPORTER_OTLP_ENDPOINT"] == local.hosted_otlp_endpoint && one(aws_lightsail_container_service_deployment_version.api[0].container).environment["PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID"] == local.hosted_otlp_instance_id
    error_message = "Enabled backend export must retain the configured endpoint and instance in the actual container."
  }

}

run "browser_only_public_metadata_does_not_change_backend_container" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = false
      frontend_enabled   = true
      stack_url          = "https://fixture.grafana.net/"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
      otlp_endpoint      = "https://gateway.grafana.net/otlp"
      otlp_instance_id   = "12345"
    }
  }
  assert {
    condition     = local.backend_runtime_environment["OTEL_EXPORTER_OTLP_ENDPOINT"] == "" && local.backend_runtime_environment["PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID"] == "" && local.backend_runtime_environment["PAWLOCAL_TELEMETRY_ENABLED"] == "false" && local.backend_runtime_environment["OTEL_SDK_DISABLED"] == "true" && one(aws_lightsail_container_service_deployment_version.api[0].container).environment == local.backend_runtime_environment && one(aws_lightsail_container_service_deployment_version.api[0].container).image == var.backend_image
    error_message = "Browser-only public metadata must leave the actual same-image backend container export settings at their null/disabled values."
  }
  assert {
    condition     = aws_ssm_parameter.configuration["grafana/otlp-endpoint"].value == var.hosted_observability.otlp_endpoint && aws_ssm_parameter.configuration["grafana/otlp-instance-id"].value == var.hosted_observability.otlp_instance_id && aws_ssm_parameter.configuration["frontend/telemetry-enabled"].value == "true" && alltrue([for s in data.aws_iam_policy_document.runtime[0].statement : !contains(flatten([s.actions]), "ssm:GetParameter") && !contains(flatten([s.actions]), "kms:Decrypt")])
    error_message = "Known public stack metadata must still be seeded without granting backend credential access."
  }
}

run "enabled_mode_discovery_omitted_otlp_bindings" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = {
      enabled            = true
      stack_url          = "https://fixture.grafana.net/"
      faro_collector_url = "https://faro.grafana.net/collect/public-key"
      kms_key_arn        = "arn:aws:kms:ap-southeast-2:111111111111:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  }
  assert {
    condition     = local.application_configuration_values["observability/enabled"] == "true" && local.application_configuration_values["grafana/otlp-endpoint"] == "https://otlp-gateway.grafana.net/otlp" && local.application_configuration_values["grafana/otlp-instance-id"] == "12345" && local.application_configuration_values["grafana/stack-url"] == "https://fixture.grafana.net/"
    error_message = "Discovered public Grafana bindings must populate SSM parameters when omitted from operator inputs."
  }
  assert {
    condition     = local.backend_runtime_environment["OTEL_SDK_DISABLED"] == "false" && local.backend_runtime_environment["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://otlp-gateway.grafana.net/otlp" && local.backend_runtime_environment["PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID"] == "12345"
    error_message = "Discovered OTLP endpoint and instance ID must populate backend runtime environment."
  }
}
