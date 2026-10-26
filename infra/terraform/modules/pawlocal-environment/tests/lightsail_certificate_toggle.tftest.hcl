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
  target          = aws_lightsail_certificate.api
  override_during = plan
  values          = { domain_validation_options = [{ domain_name = "fixture.example.test", resource_record_name = "_fixture.api-dev.example.test", resource_record_type = "CNAME", resource_record_value = "_fixture.acm-validations.aws" }] }
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
run "development_default_attached" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    environment                = "development"
    terraform_apply_role_name  = "pawlocal-development-terraform-apply"
    frontend_publish_role_name = "pawlocal-development-github-deploy"
  }
  assert {
    condition     = aws_lightsail_certificate.api.name == "pawlocal-development-api-cert" && aws_lightsail_certificate.api.domain_name == "api-dev.example.test" && one(one(aws_lightsail_container_service.api.public_domain_names).certificate).domain_names == tolist(["api-dev.example.test"])
    error_message = "The flag must change only certificate attachment, preserving valid original certificate identity and domain."
  }
  assert {
    condition     = aws_route53_record.api_certificate_validation.type == "CNAME" && toset(one([for s in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement : flatten([s.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]]) if s.Sid == "ValidateOnlyLegacyCertificateDNS"])) == toset(["_*.api-dev.example.test"])
    error_message = "Certificate validation must remain a scoped CNAME, without a public API alias."
  }
}

run "development_detached" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  variables {
    environment                  = "development"
    terraform_apply_role_name    = "pawlocal-development-terraform-apply"
    frontend_publish_role_name   = "pawlocal-development-github-deploy"
    detach_lightsail_certificate = true
  }
  assert {
    condition     = aws_lightsail_certificate.api.name == "pawlocal-development-api-cert" && aws_lightsail_certificate.api.domain_name == "api-dev.example.test" && length(aws_lightsail_container_service.api.public_domain_names) == 0
    error_message = "The flag must change only certificate attachment, preserving valid original certificate identity and domain."
  }
  assert {
    condition     = aws_route53_record.api_certificate_validation.type == "CNAME" && toset(one([for s in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement : flatten([s.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]]) if s.Sid == "ValidateOnlyLegacyCertificateDNS"])) == toset(["_*.api-dev.example.test"])
    error_message = "Certificate validation must remain a scoped CNAME, without a public API alias."
  }
}

run "production_default_attached" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  override_resource {
    target          = aws_lightsail_certificate.api
    override_during = plan
    values          = { domain_validation_options = [{ domain_name = "api.example.test", resource_record_name = "_fixture.api.example.test", resource_record_type = "CNAME", resource_record_value = "_fixture.acm-validations.aws" }] }
  }
  variables {
    environment                = "production"
    terraform_apply_role_name  = "pawlocal-production-terraform-apply"
    frontend_publish_role_name = "pawlocal-production-github-deploy"
  }
  assert {
    condition     = aws_lightsail_certificate.api.name == "pawlocal-production-api-cert" && aws_lightsail_certificate.api.domain_name == "api.example.test" && one(one(aws_lightsail_container_service.api.public_domain_names).certificate).domain_names == tolist(["api.example.test"])
    error_message = "The flag must change only certificate attachment, preserving valid original certificate identity and domain."
  }
  assert {
    condition     = aws_route53_record.api_certificate_validation.type == "CNAME" && toset(one([for s in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement : flatten([s.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]]) if s.Sid == "ValidateOnlyLegacyCertificateDNS"])) == toset(["_*.api.example.test"])
    error_message = "Certificate validation must remain a scoped CNAME, without a public API alias."
  }
}

run "production_detached" {
  command   = plan
  providers = { aws = aws.test, aws.cognito_deployment = aws.cognito_test, aws.oncall_deployment = aws.cognito_test }
  override_resource {
    target          = aws_lightsail_certificate.api
    override_during = plan
    values          = { domain_validation_options = [{ domain_name = "api.example.test", resource_record_name = "_fixture.api.example.test", resource_record_type = "CNAME", resource_record_value = "_fixture.acm-validations.aws" }] }
  }
  variables {
    environment                  = "production"
    terraform_apply_role_name    = "pawlocal-production-terraform-apply"
    frontend_publish_role_name   = "pawlocal-production-github-deploy"
    detach_lightsail_certificate = true
  }
  assert {
    condition     = aws_lightsail_certificate.api.name == "pawlocal-production-api-cert" && aws_lightsail_certificate.api.domain_name == "api.example.test" && length(aws_lightsail_container_service.api.public_domain_names) == 0
    error_message = "The flag must change only certificate attachment, preserving valid original certificate identity and domain."
  }
  assert {
    condition     = aws_route53_record.api_certificate_validation.type == "CNAME" && toset(one([for s in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement : flatten([s.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]]) if s.Sid == "ValidateOnlyLegacyCertificateDNS"])) == toset(["_*.api.example.test"])
    error_message = "Certificate validation must remain a scoped CNAME, without a public API alias."
  }
}
