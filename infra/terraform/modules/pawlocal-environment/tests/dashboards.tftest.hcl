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

override_data {
  target = data.grafana_frontend_o11y_app.selected
  values = {
    id                 = 54321
    collector_endpoint = "https://faro.grafana.net/collect/public-key"
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

run "disabled_mode_creates_zero_dashboards" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    hosted_observability = null
  }
  assert {
    condition = (
      length(grafana_dashboard.journey) == 0 &&
      length(grafana_dashboard.application) == 0 &&
      length(grafana_dashboard.dependencies) == 0 &&
      length(grafana_dashboard.releases) == 0 &&
      length(grafana_dashboard.telemetry) == 0 &&
      length(grafana_dashboard.incidents) == 0
    )
    error_message = "Disabled mode (hosted_observability = null) must create 0 dashboards."
  }
}

run "development_environment_creates_six_dashboards_scoped_to_dev" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    environment                = "development"
    terraform_apply_role_name  = "pawlocal-development-terraform-apply"
    frontend_publish_role_name = "pawlocal-development-github-deploy"
    runtime_role_arn           = "arn:aws:iam::111111111111:role/pawlocal-development-dsql-runtime"
    hosted_observability = {
      enabled   = true
      stack_url = "https://fixture.grafana.net/"
    }
  }
  assert {
    condition = (
      length(grafana_dashboard.journey) == 1 &&
      length(grafana_dashboard.application) == 1 &&
      length(grafana_dashboard.dependencies) == 1 &&
      length(grafana_dashboard.releases) == 1 &&
      length(grafana_dashboard.telemetry) == 1 &&
      length(grafana_dashboard.incidents) == 1
    )
    error_message = "Enabled development environment must create exactly 6 dashboards."
  }
  assert {
    condition = (
      grafana_dashboard.journey[0].folder == "pawlocal-development" &&
      grafana_dashboard.application[0].folder == "pawlocal-development" &&
      grafana_dashboard.dependencies[0].folder == "pawlocal-development" &&
      grafana_dashboard.releases[0].folder == "pawlocal-development" &&
      grafana_dashboard.telemetry[0].folder == "pawlocal-development" &&
      grafana_dashboard.incidents[0].folder == "pawlocal-development"
    )
    error_message = "All dashboards must be created in folder pawlocal-development."
  }
  assert {
    condition = (
      jsondecode(grafana_dashboard.journey[0].config_json).uid == "pawlocal-development-journey" &&
      jsondecode(grafana_dashboard.application[0].config_json).uid == "pawlocal-development-application" &&
      jsondecode(grafana_dashboard.dependencies[0].config_json).uid == "pawlocal-development-dependencies" &&
      jsondecode(grafana_dashboard.releases[0].config_json).uid == "pawlocal-development-releases" &&
      jsondecode(grafana_dashboard.telemetry[0].config_json).uid == "pawlocal-development-telemetry" &&
      jsondecode(grafana_dashboard.incidents[0].config_json).uid == "pawlocal-development-incidents"
    )
    error_message = "All dashboard UIDs must have the pawlocal-development-* prefix."
  }
  assert {
    condition = (
      jsondecode(grafana_dashboard.journey[0].config_json).title == "PawLocal Development - Journey" &&
      jsondecode(grafana_dashboard.application[0].config_json).title == "PawLocal Development - Application" &&
      jsondecode(grafana_dashboard.dependencies[0].config_json).title == "PawLocal Development - Dependencies" &&
      jsondecode(grafana_dashboard.releases[0].config_json).title == "PawLocal Development - Releases" &&
      jsondecode(grafana_dashboard.telemetry[0].config_json).title == "PawLocal Development - Telemetry" &&
      jsondecode(grafana_dashboard.incidents[0].config_json).title == "PawLocal Development - Incidents"
    )
    error_message = "All dashboard titles must be formatted as PawLocal Development - <Name>."
  }
  assert {
    condition = alltrue([
      strcontains(grafana_dashboard.journey[0].config_json, "environment=\\\"development\\\""),
      strcontains(grafana_dashboard.application[0].config_json, "environment=\\\"development\\\""),
      strcontains(grafana_dashboard.dependencies[0].config_json, "environment=\\\"development\\\""),
      strcontains(grafana_dashboard.releases[0].config_json, "environment=\\\"development\\\""),
      strcontains(grafana_dashboard.telemetry[0].config_json, "environment=\\\"development\\\""),
      strcontains(grafana_dashboard.incidents[0].config_json, "environment=\\\"development\\\""),
    ])
    error_message = "All dashboards must contain queries with environment=\"development\"."
  }
  assert {
    condition = alltrue([
      grafana_dashboard.journey[0].overwrite == false,
      grafana_dashboard.application[0].overwrite == false,
      grafana_dashboard.dependencies[0].overwrite == false,
      grafana_dashboard.releases[0].overwrite == false,
      grafana_dashboard.telemetry[0].overwrite == false,
      grafana_dashboard.incidents[0].overwrite == false,
    ])
    error_message = "Dashboards must have overwrite disabled to prevent foreign UID collision adoption."
  }
  assert {
    condition     = strcontains(grafana_dashboard.telemetry[0].config_json, "grafanacloud-usage")
    error_message = "Telemetry quota panels must bind to grafanacloud-usage datasource."
  }
}

run "production_environment_creates_six_dashboards_scoped_to_prod_never_dev" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    environment                = "production"
    terraform_apply_role_name  = "pawlocal-production-terraform-apply"
    frontend_publish_role_name = "pawlocal-production-github-deploy"
    runtime_role_arn           = "arn:aws:iam::111111111111:role/pawlocal-production-dsql-runtime"
    hosted_observability = {
      enabled   = true
      stack_url = "https://fixture.grafana.net/"
    }
  }
  assert {
    condition = (
      length(grafana_dashboard.journey) == 1 &&
      length(grafana_dashboard.application) == 1 &&
      length(grafana_dashboard.dependencies) == 1 &&
      length(grafana_dashboard.releases) == 1 &&
      length(grafana_dashboard.telemetry) == 1 &&
      length(grafana_dashboard.incidents) == 1
    )
    error_message = "Enabled production environment must create exactly 6 dashboards."
  }
  assert {
    condition = (
      grafana_dashboard.journey[0].folder == "pawlocal-production" &&
      grafana_dashboard.application[0].folder == "pawlocal-production" &&
      grafana_dashboard.dependencies[0].folder == "pawlocal-production" &&
      grafana_dashboard.releases[0].folder == "pawlocal-production" &&
      grafana_dashboard.telemetry[0].folder == "pawlocal-production" &&
      grafana_dashboard.incidents[0].folder == "pawlocal-production"
    )
    error_message = "All dashboards must be created in folder pawlocal-production."
  }
  assert {
    condition = (
      jsondecode(grafana_dashboard.journey[0].config_json).uid == "pawlocal-production-journey" &&
      jsondecode(grafana_dashboard.application[0].config_json).uid == "pawlocal-production-application" &&
      jsondecode(grafana_dashboard.dependencies[0].config_json).uid == "pawlocal-production-dependencies" &&
      jsondecode(grafana_dashboard.releases[0].config_json).uid == "pawlocal-production-releases" &&
      jsondecode(grafana_dashboard.telemetry[0].config_json).uid == "pawlocal-production-telemetry" &&
      jsondecode(grafana_dashboard.incidents[0].config_json).uid == "pawlocal-production-incidents"
    )
    error_message = "All dashboard UIDs must have the pawlocal-production-* prefix."
  }
  assert {
    condition = (
      jsondecode(grafana_dashboard.journey[0].config_json).title == "PawLocal Production - Journey" &&
      jsondecode(grafana_dashboard.application[0].config_json).title == "PawLocal Production - Application" &&
      jsondecode(grafana_dashboard.dependencies[0].config_json).title == "PawLocal Production - Dependencies" &&
      jsondecode(grafana_dashboard.releases[0].config_json).title == "PawLocal Production - Releases" &&
      jsondecode(grafana_dashboard.telemetry[0].config_json).title == "PawLocal Production - Telemetry" &&
      jsondecode(grafana_dashboard.incidents[0].config_json).title == "PawLocal Production - Incidents"
    )
    error_message = "All dashboard titles must be formatted as PawLocal Production - <Name>."
  }
  assert {
    condition = alltrue([
      strcontains(grafana_dashboard.journey[0].config_json, "environment=\\\"production\\\""),
      strcontains(grafana_dashboard.application[0].config_json, "environment=\\\"production\\\""),
      strcontains(grafana_dashboard.dependencies[0].config_json, "environment=\\\"production\\\""),
      strcontains(grafana_dashboard.releases[0].config_json, "environment=\\\"production\\\""),
      strcontains(grafana_dashboard.telemetry[0].config_json, "environment=\\\"production\\\""),
      strcontains(grafana_dashboard.incidents[0].config_json, "environment=\\\"production\\\""),
    ])
    error_message = "All production dashboards must contain queries with environment=\"production\"."
  }
  assert {
    condition = alltrue([
      !strcontains(grafana_dashboard.journey[0].config_json, "development"),
      !strcontains(grafana_dashboard.application[0].config_json, "development"),
      !strcontains(grafana_dashboard.dependencies[0].config_json, "development"),
      !strcontains(grafana_dashboard.releases[0].config_json, "development"),
      !strcontains(grafana_dashboard.telemetry[0].config_json, "development"),
      !strcontains(grafana_dashboard.incidents[0].config_json, "development"),
    ])
    error_message = "Production dashboards must NEVER reference or display development data."
  }
  assert {
    condition = alltrue([
      grafana_dashboard.journey[0].overwrite == false,
      grafana_dashboard.application[0].overwrite == false,
      grafana_dashboard.dependencies[0].overwrite == false,
      grafana_dashboard.releases[0].overwrite == false,
      grafana_dashboard.telemetry[0].overwrite == false,
      grafana_dashboard.incidents[0].overwrite == false,
    ])
    error_message = "Dashboards must have overwrite disabled to prevent foreign UID collision adoption."
  }
  assert {
    condition     = strcontains(grafana_dashboard.telemetry[0].config_json, "grafanacloud-usage")
    error_message = "Telemetry quota panels must bind to grafanacloud-usage datasource."
  }
}
