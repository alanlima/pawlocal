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
      strcontains(data.aws_iam_policy_document.application.minified_json, "s3:PutBucketPublicAccessBlock") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "s3:PutPublicAccessBlock") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "\"s3:Get*\"") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "dsql:TagResource") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "cloudfront:CreateFunction") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "cloudfront:TagResource") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "cloudfront:UntagResource")
    )
    error_message = "The application policy must authorize only the reviewed tagged-create handoffs and must not grant broad S3 reads or authorization-tag removal."
  }

  assert {
    condition = (
      toset(one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        flatten([statement.Action])
        if statement.Sid == "ManageOnlyMatchingFrontendBucketName"
        ])) == toset([
        "s3:DeleteBucket", "s3:PutBucketOwnershipControls", "s3:PutBucketPolicy",
        "s3:PutBucketPublicAccessBlock", "s3:PutEncryptionConfiguration"
      ]) &&
      !contains(keys(one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement : statement
        if statement.Sid == "ManageOnlyMatchingFrontendBucketName"
      ])), "Condition")
    )
    error_message = "Immediate post-create S3 configuration must use only the generated environment bucket-name boundary because resource-tag authorization is not yet consistent."
  }

  assert {
    condition = alltrue([
      for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
      !contains(keys(statement.Condition), "Null") &&
      statement.Condition.StringEquals["aws:ResourceTag/project"] == "pawlocal" &&
      statement.Condition.StringEquals["aws:ResourceTag/environment"] == "development"
      if contains(["TagOnlyNewEnvironmentResources", "CreateAndTagOnlyNewEnvironmentDSQLCluster"], statement.Sid)
    ])
    error_message = "Create-time dependent TagResource authorization must match the surfaced authorization tags without requiring them to be absent."
  }

  assert {
    condition = alltrue([
      for key, value in local.common_tags :
      strcontains(data.aws_iam_policy_document.application.minified_json, "aws:RequestTag/${key}") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, value)
    ])
    error_message = "Tagged creation must require every expected application tag value."
  }

  assert {
    condition = contains(
      flatten(one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        [statement.Resource]
        if statement.Sid == "TagOnlyNewEnvironmentResources"
      ])),
      "arn:aws:lightsail:ap-southeast-2:111111111111:ContainerService/*"
    )
    error_message = "Lightsail container-service create-time tagging must use AWS's pre-creation ContainerService/* authorization resource."
  }

  assert {
    condition = (
      toset(one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        flatten([statement.Action])
        if statement.Sid == "CreateAndTagOnlyNewEnvironmentDSQLCluster"
      ])) == toset(["dsql:CreateCluster", "dsql:TagResource"])
    )
    error_message = "DSQL create and its dependent TagResource authorization must share one service-specific statement."
  }

  assert {
    condition = (
      toset(one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        statement.Condition["ForAllValues:StringEquals"]["aws:TagKeys"]
        if statement.Sid == "CreateAndTagOnlyNewEnvironmentDSQLCluster"
      ])) == toset(keys(local.dsql_tags)) &&
      alltrue([
        for key, value in local.dsql_tags :
        one([
          for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
          statement.Condition.StringEquals["aws:RequestTag/${key}"]
          if statement.Sid == "CreateAndTagOnlyNewEnvironmentDSQLCluster"
        ]) == value
      ])
    )
    error_message = "The rendered DSQL authorization must fail closed unless all eight actual cluster tag keys and values are present."
  }

  assert {
    condition = (
      one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        statement.Condition.StringEquals["aws:RequestTag/Name"]
        if statement.Sid == "CreateAndTagOnlyNewEnvironmentDSQLCluster"
      ]) == "pawlocal-development" &&
      one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        statement.Condition.StringEquals["aws:RequestTag/purpose"]
        if statement.Sid == "CreateAndTagOnlyNewEnvironmentDSQLCluster"
      ]) == "pawlocal-app-database"
    )
    error_message = "Missing or incorrect DSQL Name/purpose request tags must not satisfy the rendered allow statement."
  }
}
