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

run "tagged_create_permissions_are_size_safe" {
  command = plan

  providers = {
    aws = aws.test
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
  }

  assert {
    condition     = length(data.aws_iam_policy_document.application.minified_json) <= local.iam_managed_policy_max_bytes
    error_message = "The rendered environment application policy must stay within IAM's 6144-byte managed-policy limit."
  }

  assert {
    condition = (
      strcontains(data.aws_iam_policy_document.application.minified_json, "s3:CreateBucket") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "s3:TagResource") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "s3:PutBucketTagging") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "s3:ListTagsForResource") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "\"s3:Get*\"") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "dsql:TagResource") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "cloudfront:CreateFunction") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "cloudfront:TagResource") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "cloudfront:UntagResource")
    )
    error_message = "The application policy must authorize only the reviewed tagged-create handoffs and must not grant broad S3 reads or authorization-tag removal."
  }

  assert {
    condition = alltrue([
      for key, value in local.common_tags :
      strcontains(data.aws_iam_policy_document.application.minified_json, "aws:RequestTag/${key}") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, value)
    ])
    error_message = "Tagged creation must require every expected application tag value."
  }
}
