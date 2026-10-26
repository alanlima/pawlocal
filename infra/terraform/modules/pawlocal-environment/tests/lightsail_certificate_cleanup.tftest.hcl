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

variables {
  environment                = "development"
  aws_region                 = "ap-southeast-2"
  root_domain                = "example.test"
  route53_zone_id            = "ZTEST"
  cloudfront_certificate_arn = "arn:aws:acm:us-east-1:111111111111:certificate/test"
  cognito_password_policy    = { minimum_length = 8, require_lowercase = false, require_uppercase = false, require_numbers = false }
  terraform_apply_role_name  = "pawlocal-development-terraform-apply"
  frontend_publish_role_name = "pawlocal-development-github-deploy"
  container_power            = "micro"
}
run "development_fresh_without_certificate" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    environment                = "development"
    terraform_apply_role_name  = "pawlocal-development-terraform-apply"
    frontend_publish_role_name = "pawlocal-development-github-deploy"
  }
  assert {
    condition     = length(aws_lightsail_container_service.api.public_domain_names) == 0 && aws_lightsail_container_service.api.name == "pawlocal-development-api" && !strcontains(data.aws_iam_policy_document.application.minified_json, "lightsail:CreateCertificate") && !strcontains(data.aws_iam_policy_document.application.minified_json, "ValidateOnlyLegacyCertificateDNS") && strcontains(data.aws_iam_policy_document.application.minified_json, "lightsail:DeleteCertificate")
    error_message = "Fresh Foundation must preserve service identity without certificate attachment/creation authority while retaining lifecycle deletion."
  }
}
run "production_fresh_without_certificate" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    environment                = "production"
    terraform_apply_role_name  = "pawlocal-production-terraform-apply"
    frontend_publish_role_name = "pawlocal-production-github-deploy"
  }
  assert {
    condition     = length(aws_lightsail_container_service.api.public_domain_names) == 0 && aws_lightsail_container_service.api.name == "pawlocal-production-api" && !strcontains(data.aws_iam_policy_document.application.minified_json, "lightsail:CreateCertificate") && !strcontains(data.aws_iam_policy_document.application.minified_json, "ValidateOnlyLegacyCertificateDNS") && strcontains(data.aws_iam_policy_document.application.minified_json, "lightsail:DeleteCertificate")
    error_message = "Fresh Foundation must preserve service identity without certificate attachment/creation authority while retaining lifecycle deletion."
  }
}
