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

run "tagged_create_permissions_are_size_safe" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
    aws.oncall_deployment  = aws.cognito_test
  }

  variables {
    environment                = "development"
    aws_region                 = "ap-southeast-2"
    project_name               = "pawhub"
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
    condition     = length(data.aws_iam_policy_document.application.minified_json) <= local.iam_managed_policy_max_bytes
    error_message = "The rendered environment application policy must stay within IAM's 6144-byte managed-policy limit."
  }

  assert {
    condition = (
      toset(keys(local.resource_suffixes)) == toset(["container_service"]) &&
      local.resource_suffixes.container_service == "api" &&
      local.cognito_pre_sign_up_name == "pawlocal-development-cognito-pre-signup" &&
      local.resource_names.container_service == "pawlocal-development-api" &&
      aws_lightsail_container_service.api.name == "pawlocal-development-api" &&
      length(aws_lightsail_container_service.api.public_domain_names) == 0
    )
    error_message = "Lightsail must retain its service identity without a custom-domain certificate."
  }

  assert {
    condition = (
      !strcontains(data.aws_iam_policy_document.application.minified_json, "lightsail:CreateCertificate") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "Certificate/*") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "lightsail:DeleteCertificate") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, "lightsail:UpdateContainerService") &&
      toset(flatten([one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        statement.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]
        if statement.Sid == "ChangeOnlyEnvironmentDNSNames"
      ])])) == toset(["pawlocal-dev.example.test"]) &&
      toset(flatten([one([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement :
        statement.Condition["ForAllValues:StringEquals"]["route53:ChangeResourceRecordSetsRecordTypes"]
        if statement.Sid == "ChangeOnlyEnvironmentDNSNames"
      ])])) == toset(["A", "AAAA"])
    )
    error_message = "Application permissions must manage only frontend DNS and retain certificate deletion/service detachment without obsolete certificate creation or tagging; bootstrap owns independent lifecycle DNS deletion."
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
      statement.Condition.StringEquals["aws:ResourceTag/project"] == "pawhub" &&
      statement.Condition.StringEquals["aws:ResourceTag/environment"] == "development"
      if contains(["TagOnlyNewEnvironmentResources", "CreateAndTagOnlyNewEnvironmentDSQLCluster"], statement.Sid)
    ])
    error_message = "Create-time dependent TagResource authorization must match the surfaced authorization tags without requiring them to be absent."
  }

  assert {
    condition = local.common_tags.project == "pawhub" && alltrue([
      for key, value in local.common_tags :
      strcontains(data.aws_iam_policy_document.application.minified_json, "aws:RequestTag/${key}") &&
      strcontains(data.aws_iam_policy_document.application.minified_json, value)
      ]) && alltrue(flatten([
        for statement in jsondecode(data.aws_iam_policy_document.application.minified_json).Statement : [
          for operator, conditions in try(statement.Condition, {}) : [
            for variable, values in conditions : toset(flatten([values])) == toset(["pawhub"])
            if contains(["aws:RequestTag/project", "aws:ResourceTag/project"], variable)
          ]
        ]
    ]))
    error_message = "A non-default project_name must propagate through common tags and every application policy project-tag condition."
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

run "runtime_identity_activates_protected_setup_and_deployment" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
    aws.oncall_deployment  = aws.cognito_test
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
    runtime_role_arn           = "arn:aws:iam::111111111111:role/pawlocal-development-dsql-runtime"
    backend_image              = "ghcr.io/alanlima/pawlocal-api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    container_power            = "micro"
  }

  override_resource {
    target          = aws_dsql_cluster.application
    override_during = plan
    values = {
      arn        = "arn:aws:dsql:ap-southeast-2:111111111111:cluster/aaaaaaaaaaaaaaaaaaaaaaaaaa"
      identifier = "aaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  }

  assert {
    condition = (
      length(module.dsql_post_apply_setup) == 1 &&
      length(aws_iam_policy.dsql_setup) == 1 &&
      length(aws_iam_role_policy_attachment.dsql_setup) == 1 &&
      length(aws_lightsail_container_service_deployment_version.api) == 1
    )
    error_message = "A nonempty matching runtime identity and backend image must activate one protected setup and one gated deployment."
  }

  assert {
    condition = module.dsql_post_apply_setup[0].trigger_digests == {
      cluster_identity_sha256 = sha256("arn:aws:dsql:ap-southeast-2:111111111111:cluster/aaaaaaaaaaaaaaaaaaaaaaaaaa")
      runtime_identity_sha256 = sha256("arn:aws:iam::111111111111:role/pawlocal-development-dsql-runtime")
      setup_revision_sha256   = sha256("dsql-setup-v1-dsql_0001_initial")
    }
    error_message = "The active setup lifecycle must be controlled only by cluster, runtime identity, and explicit setup revision digests."
  }
}

run "production_resource_names_use_normalized_suffixes" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
    aws.oncall_deployment  = aws.cognito_test
  }

  variables {
    environment                = "production"
    aws_region                 = "ap-southeast-2"
    root_domain                = "example.test"
    route53_zone_id            = "ZTEST"
    cloudfront_certificate_arn = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    cognito_password_policy = {
      minimum_length    = 12
      require_lowercase = true
      require_uppercase = true
      require_numbers   = true
    }
    terraform_apply_role_name  = "pawlocal-production-terraform-apply"
    frontend_publish_role_name = "pawlocal-production-github-deploy"
    container_power            = "medium"
  }

  assert {
    condition = (
      local.common_tags.project == "pawlocal" &&
      local.resource_names.container_service == "pawlocal-production-api" &&
      aws_lightsail_container_service.api.name == "pawlocal-production-api"
    )
    error_message = "The default project tag must remain pawlocal while production resource names use the normalized suffixes."
  }
}

run "project_name_over_policy_budget_is_rejected" {
  command = plan

  providers = {
    aws                    = aws.test
    aws.cognito_deployment = aws.cognito_test
    aws.oncall_deployment  = aws.cognito_test
  }

  variables {
    environment                = "development"
    aws_region                 = "ap-southeast-2"
    project_name               = "pawlocalx"
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

  expect_failures = [var.project_name]
}
