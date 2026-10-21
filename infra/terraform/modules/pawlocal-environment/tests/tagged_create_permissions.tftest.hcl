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
    environment                  = "development"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    terraform_apply_role_name    = "pawlocal-development-terraform-apply"
    frontend_publish_role_name   = "pawlocal-development-github-deploy"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::111111111111:role/pawlocal-development-cognito-pre-signup"
    container_power              = "micro"
  }

  assert {
    condition     = length(data.aws_iam_policy_document.application.minified_json) <= local.iam_managed_policy_max_bytes
    error_message = "The rendered environment application policy must stay within IAM's 6144-byte managed-policy limit."
  }

  assert {
    condition     = length(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json) <= local.iam_managed_policy_max_bytes
    error_message = "The dedicated Cognito pre sign-up deployment policy must stay within IAM's 6144-byte managed-policy limit."
  }

  assert {
    condition = (
      toset(one([
        for statement in jsondecode(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json).Statement :
        flatten([statement.Action])
        if statement.Sid == "ManageOnlyMatchingCognitoPreSignUpFunction"
        ])) == toset([
        "lambda:AddPermission", "lambda:CreateFunction", "lambda:DeleteFunction", "lambda:GetFunction",
        "lambda:GetFunctionCodeSigningConfig", "lambda:GetPolicy", "lambda:GetRuntimeManagementConfig",
        "lambda:ListTags", "lambda:ListVersionsByFunction", "lambda:RemovePermission", "lambda:TagResource",
        "lambda:UntagResource", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration"
      ]) &&
      toset(one([
        for statement in jsondecode(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json).Statement :
        flatten([statement.Resource])
        if statement.Sid == "ManageOnlyMatchingCognitoPreSignUpFunction"
      ])) == toset(["arn:aws:lambda:ap-southeast-2:111111111111:function:pawlocal-development-cognito-pre-signup"])
    )
    error_message = "The environment identity policy must grant only the reviewed Lambda lifecycle on the exact matching function."
  }

  assert {
    condition = (
      toset(one([
        for statement in jsondecode(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json).Statement :
        flatten([statement.Action])
        if statement.Sid == "ManageOnlyMatchingCognitoPreSignUpLogGroup"
        ])) == toset([
        "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:ListTagsForResource",
        "logs:PutRetentionPolicy", "logs:TagResource", "logs:UntagResource"
      ]) &&
      toset(one([
        for statement in jsondecode(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json).Statement :
        flatten([statement.Resource])
        if statement.Sid == "ManageOnlyMatchingCognitoPreSignUpLogGroup"
        ])) == toset([
        "arn:aws:logs:ap-southeast-2:111111111111:log-group:/aws/lambda/pawlocal-development-cognito-pre-signup",
        "arn:aws:logs:ap-southeast-2:111111111111:log-group:/aws/lambda/pawlocal-development-cognito-pre-signup:*"
      ])
    )
    error_message = "The environment identity policy must grant only the reviewed log-group lifecycle on the exact matching group."
  }

  assert {
    condition = (
      one([
        for statement in jsondecode(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json).Statement :
        statement.Resource
        if statement.Sid == "PassOnlyMatchingCognitoPreSignUpRole"
      ]) == "arn:aws:iam::111111111111:role/pawlocal-development-cognito-pre-signup" &&
      one([
        for statement in jsondecode(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json).Statement :
        statement.Condition.StringEquals["iam:PassedToService"]
        if statement.Sid == "PassOnlyMatchingCognitoPreSignUpRole"
      ]) == "lambda.amazonaws.com" &&
      !strcontains(data.aws_iam_policy_document.cognito_pre_sign_up_deployment.minified_json, "pawlocal-production-cognito-pre-signup") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "lambda:") &&
      !strcontains(data.aws_iam_policy_document.application.minified_json, "iam:PassRole")
    )
    error_message = "PassRole must target only the matching bootstrap role and Lambda service, isolated from the general application policy."
  }

  assert {
    condition = (
      toset(keys(local.resource_suffixes)) == toset(["cert", "container_service"]) &&
      local.resource_suffixes.cert == "cert" &&
      local.resource_suffixes.container_service == "api" &&
      local.resource_names.cert == "pawlocal-development-api-cert" &&
      local.resource_names.container_service == "pawlocal-development-api" &&
      aws_lightsail_container_service.api.name == "pawlocal-development-api" &&
      aws_lightsail_certificate.api.name == "pawlocal-development-api-cert" &&
      aws_lightsail_container_service.api.name != aws_lightsail_certificate.api.name
    )
    error_message = "Lightsail names must use the normalized suffix map and keep the service and certificate names distinct."
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

run "cross_environment_cognito_role_is_rejected" {
  command = plan

  providers = {
    aws = aws.test
  }

  variables {
    environment                  = "development"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    terraform_apply_role_name    = "pawlocal-development-terraform-apply"
    frontend_publish_role_name   = "pawlocal-development-github-deploy"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::111111111111:role/pawlocal-production-cognito-pre-signup"
    container_power              = "micro"
  }

  expect_failures = [var.cognito_pre_sign_up_role_arn]
}

run "runtime_identity_activates_protected_setup_and_deployment" {
  command = plan

  providers = {
    aws = aws.test
  }

  variables {
    environment                  = "development"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    terraform_apply_role_name    = "pawlocal-development-terraform-apply"
    frontend_publish_role_name   = "pawlocal-development-github-deploy"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::111111111111:role/pawlocal-development-cognito-pre-signup"
    runtime_role_arn             = "arn:aws:iam::111111111111:role/pawlocal-development-dsql-runtime"
    backend_image                = "ghcr.io/alanlima/pawlocal-api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    container_power              = "micro"
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
    aws = aws.test
  }

  variables {
    environment                  = "production"
    aws_region                   = "ap-southeast-2"
    root_domain                  = "example.test"
    route53_zone_id              = "ZTEST"
    cloudfront_certificate_arn   = "arn:aws:acm:us-east-1:111111111111:certificate/test"
    terraform_apply_role_name    = "pawlocal-production-terraform-apply"
    frontend_publish_role_name   = "pawlocal-production-github-deploy"
    cognito_pre_sign_up_role_arn = "arn:aws:iam::111111111111:role/pawlocal-production-cognito-pre-signup"
    container_power              = "medium"
  }

  assert {
    condition = (
      local.resource_names.cert == "pawlocal-production-api-cert" &&
      local.resource_names.container_service == "pawlocal-production-api" &&
      aws_lightsail_certificate.api.name == "pawlocal-production-api-cert" &&
      aws_lightsail_container_service.api.name == "pawlocal-production-api"
    )
    error_message = "Production Lightsail names must use the same normalized cert and container-service suffixes."
  }
}
