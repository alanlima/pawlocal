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
  values = { account_id = "111111111111" }
}

override_data {
  target = data.aws_partition.current
  values = { partition = "aws" }
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
}

run "foundation_publishes_only_available_application_values" {
  command = plan
  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  override_resource {
    target          = aws_route53_record.frontend_a
    override_during = plan
    values          = { fqdn = "pawlocal-dev.fixture.example." }
  }

  assert {
    condition = length(aws_ssm_parameter.configuration) == 10 && alltrue([
      for suffix, parameter in aws_ssm_parameter.configuration :
      parameter.name == "/pawlocal/development/config/${suffix}" &&
      parameter.type == "String" && parameter.tier == "Standard" && parameter.overwrite == null &&
      parameter.tags.project == var.project_name && parameter.tags.environment == var.environment &&
      parameter.tags["configuration-access"] == "github-public" &&
      !startswith(suffix, "iam/") && !startswith(suffix, "aws/") && !startswith(suffix, "terraform/")
    ]) && !contains(keys(aws_ssm_parameter.configuration), "api/base-url") && !contains(keys(aws_ssm_parameter.configuration), "api/health-url")
    error_message = "Foundation must publish only actual available application keys; absent managed API DNS cannot be claimed ready or bootstrap-owned keys adopted."
  }

  assert {
    condition = (aws_ssm_parameter.configuration["frontend/base-url"].value == "https://pawlocal-dev.fixture.example" &&
      aws_ssm_parameter.configuration["auth/client-id"].value == "fixture-client" &&
      aws_ssm_parameter.configuration["auth/domain"].value == "https://pawlocal-development-c0ffee.auth.ap-southeast-2.amazoncognito.com" &&
      aws_ssm_parameter.configuration["auth/redirect-uri"].value == "https://pawlocal-dev.fixture.example/auth/callback" &&
      aws_ssm_parameter.configuration["auth/logout-uri"].value == "https://pawlocal-dev.fixture.example/" &&
    split(" ", aws_ssm_parameter.configuration["auth/scopes"].value) == sort(tolist(aws_cognito_user_pool_client.browser.allowed_oauth_scopes)))
    error_message = "Canonical public values must come from the actual managed DNS/domain/browser-client attributes, including callback/logout and space-separated scopes."
  }

  assert {
    condition = (length(jsondecode(data.aws_iam_policy_document.configuration.minified_json).Statement) == 1 &&
      toset(flatten([jsondecode(data.aws_iam_policy_document.configuration.minified_json).Statement[0].Action])) == toset(["ssm:GetParameter", "ssm:ListTagsForResource", "ssm:PutParameter", "ssm:DeleteParameter", "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource"]) &&
      length(jsondecode(data.aws_iam_policy_document.configuration.minified_json).Statement[0].Resource) == 12 &&
      alltrue([for arn in jsondecode(data.aws_iam_policy_document.configuration.minified_json).Statement[0].Resource : startswith(arn, "arn:aws:ssm:ap-southeast-2:111111111111:parameter/pawlocal/development/config/") && !strcontains(arn, "*") && !strcontains(arn, "/iam/") && !strcontains(arn, "/aws/") && !strcontains(arn, "/terraform/")]) &&
    aws_iam_role_policy_attachment.configuration.role == "pawlocal-development-terraform-apply")
    error_message = "The matching application state may grant only exact-key lifecycle actions on its own 12 keys, never another account/environment or bootstrap keys."
  }
}

run "converged_production_publishes_its_own_managed_api_values" {
  command = plan
  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
  }

  variables {
    environment                = "production"
    terraform_apply_role_name  = "pawlocal-production-terraform-apply"
    frontend_publish_role_name = "pawlocal-production-github-deploy"
    runtime_role_arn           = "arn:aws:iam::111111111111:role/pawlocal-production-dsql-runtime"
    backend_image              = "ghcr.io/alanlima/pawlocal-api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  override_resource {
    target          = aws_route53_record.frontend_a
    override_during = plan
    values          = { fqdn = "pawlocal.fixture.example." }
  }

  override_resource {
    target          = aws_route53_record.api[0]
    override_during = plan
    values          = { fqdn = "api.fixture.example." }
  }

  assert {
    condition = (length(aws_ssm_parameter.configuration) == 12 && alltrue([
      for suffix, parameter in aws_ssm_parameter.configuration : parameter.name == "/pawlocal/production/config/${suffix}" &&
      parameter.type == "String" && parameter.tags.project == var.project_name &&
      parameter.tags.environment == "production" && parameter.tags["configuration-access"] == "github-public"
      ]) && aws_ssm_parameter.configuration["api/base-url"].value == "https://api.fixture.example/api/v1" &&
      aws_ssm_parameter.configuration["api/health-url"].value == "https://api.fixture.example/health" &&
      output.targets.api_base_url == "https://api.fixture.example/api/v1" &&
      output.targets.cognito_domain == "https://pawlocal-production-c0ffee.auth.ap-southeast-2.amazoncognito.com" &&
    aws_iam_role_policy_attachment.configuration.role == "pawlocal-production-terraform-apply")
    error_message = "Converged production must publish all 12 matching sources in canonical formats without development contamination."
  }
}
