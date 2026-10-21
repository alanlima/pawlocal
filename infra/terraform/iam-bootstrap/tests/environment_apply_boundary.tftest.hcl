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

provider "aws" {
  alias                       = "test"
  region                      = "ap-southeast-2"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

run "environment_apply_boundaries_fit_and_stay_isolated" {
  command = plan

  providers = {
    aws = aws.test
  }

  variables {
    terraform_state_bucket_name = "test-state-bucket"
    github_repository           = "example/pawlocal"
    github_owner_id             = "1"
    github_repository_id        = "2"
    manage_github_oidc_provider = true
    route53_zone_id             = "ZTEST"
    domain_name                 = "example.test"
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      length(policy.minified_json) < 6144 &&
      length(policy.minified_json) <= local.environment_apply_boundary_max_bytes
    ])
    error_message = "Each minified environment apply boundary must stay below both the 6144-byte AWS limit and the 6050-byte repository budget."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "pawlocal/${environment}/terraform.tfstate") &&
      strcontains(policy.minified_json, "plans/${environment}/*") &&
      !strcontains(policy.minified_json, "pawlocal/${environment == "development" ? "production" : "development"}/terraform.tfstate") &&
      !strcontains(policy.minified_json, "plans/${environment == "development" ? "production" : "development"}/*")
    ])
    error_message = "Each boundary must remain limited to its matching state key and plan prefix."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "policy/pawlocal-${environment}-application") &&
      strcontains(policy.minified_json, "policy/pawlocal-${environment}-frontend-publish") &&
      strcontains(policy.minified_json, "role/pawlocal-${environment}-terraform-apply") &&
      strcontains(policy.minified_json, "role/pawlocal-${environment}-github-deploy") &&
      !strcontains(policy.minified_json, "policy/pawlocal-${environment}-runtime") &&
      !strcontains(policy.minified_json, "role/pawlocal-${environment}-dsql-runtime") &&
      !strcontains(policy.minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Initial-stage managed-policy administration and attachments must stay fixed to the two policies and matching roles that exist before a runtime cluster is handed off."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "aws:ResourceTag/project") &&
      strcontains(policy.minified_json, "aws:ResourceTag/environment") &&
      strcontains(policy.minified_json, "aws:RequestTag/project") &&
      strcontains(policy.minified_json, "aws:RequestTag/environment") &&
      strcontains(policy.minified_json, environment) &&
      !strcontains(policy.minified_json, "lightsail:UntagResource") &&
      !strcontains(policy.minified_json, "cloudfront:UntagResource")
    ])
    error_message = "Application mutation must remain tag-conditioned and authorization tags must not be removable."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "s3:CreateBucket") &&
      strcontains(policy.minified_json, "s3:TagResource") &&
      strcontains(policy.minified_json, "s3:PutBucketTagging") &&
      strcontains(policy.minified_json, "s3:ListTagsForResource") &&
      strcontains(policy.minified_json, "s3:GetBucket*") &&
      strcontains(policy.minified_json, "s3:Get*Configuration") &&
      !strcontains(policy.minified_json, "\"s3:Get*\"") &&
      strcontains(policy.minified_json, "aws:TagKeys") &&
      strcontains(policy.minified_json, "dsql:TagResource") &&
      strcontains(policy.minified_json, "cloudfront:CreateDistribution") &&
      strcontains(policy.minified_json, "cloudfront:TagResource") &&
      strcontains(policy.minified_json, "cloudfront:CreateOriginAccessControl") &&
      strcontains(policy.minified_json, "cloudfront:CreateFunction") &&
      strcontains(policy.minified_json, "cloudfront:DescribeFunction") &&
      strcontains(policy.minified_json, "cloudfront:Get*") &&
      strcontains(policy.minified_json, "cloudfront:List*")
    ])
    error_message = "Tagged create dependencies, name-scoped S3 pre-tag reads, and the initial CloudFront handoff must remain available without a broad s3:Get* grant."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "dsql:CreateCluster") &&
        contains(flatten([statement.Action]), "dsql:TagResource") &&
        toset(statement.Condition["ForAllValues:StringEquals"]["aws:TagKeys"]) == toset(keys(local.environment_dsql_tags[environment])) &&
        alltrue([
          for key, value in local.environment_dsql_tags[environment] :
          statement.Condition.StringEquals["aws:RequestTag/${key}"] == value
        ])
      ]) == 1
    ])
    error_message = "Each initial boundary must admit DSQL create/tag only with the actual eight-key environment tag set and exact values."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      one([
        for statement in jsondecode(policy.minified_json).Statement :
        statement.Condition.StringEquals["aws:RequestTag/Name"] == "pawlocal-${environment}" &&
        statement.Condition.StringEquals["aws:RequestTag/purpose"] == "pawlocal-app-database"
        if contains(flatten([statement.Action]), "dsql:CreateCluster")
      ])
    ])
    error_message = "Missing or incorrect DSQL Name/purpose request tags must not satisfy an initial boundary allow statement."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      !strcontains(policy.minified_json, "iam:CreateRole") &&
      !strcontains(policy.minified_json, "iam:DeleteRole") &&
      !strcontains(policy.minified_json, "iam:UpdateAssumeRolePolicy") &&
      !strcontains(policy.minified_json, "iam:PutRolePermissionsBoundary") &&
      !strcontains(policy.minified_json, "iam:DeleteRolePermissionsBoundary") &&
      !strcontains(policy.minified_json, "iam:PassRole")
    ])
    error_message = "The boundary must not authorize role lifecycle, trust, boundary, or PassRole mutation."
  }
}

run "runtime_stage_boundaries_fit_and_stay_isolated" {
  command = plan

  providers = {
    aws = aws.test
  }

  variables {
    terraform_state_bucket_name  = "test-state-bucket"
    github_repository            = "example/pawlocal"
    github_owner_id              = "1"
    github_repository_id         = "2"
    manage_github_oidc_provider  = true
    route53_zone_id              = "ZTEST"
    domain_name                  = "example.test"
    development_distribution_arn = "arn:aws:cloudfront::111111111111:distribution/DEVELOPMENT"
    production_distribution_arn  = "arn:aws:cloudfront::111111111111:distribution/PRODUCTION"
    development_oac_arn          = "arn:aws:cloudfront::111111111111:origin-access-control/DEVELOPMENT"
    production_oac_arn           = "arn:aws:cloudfront::111111111111:origin-access-control/PRODUCTION"
    development_dsql_cluster_arn = "arn:aws:dsql:ap-southeast-2:111111111111:cluster/development"
    production_dsql_cluster_arn  = "arn:aws:dsql:ap-southeast-2:111111111111:cluster/production"
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      length(policy.minified_json) < 6144 &&
      length(policy.minified_json) <= local.environment_apply_boundary_max_bytes
    ])
    error_message = "Each runtime-stage apply boundary must stay below both the 6144-byte AWS limit and the 6050-byte repository budget."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "policy/pawlocal-${environment}-application") &&
      strcontains(policy.minified_json, "policy/pawlocal-${environment}-frontend-publish") &&
      strcontains(policy.minified_json, "policy/pawlocal-${environment}-runtime") &&
      strcontains(policy.minified_json, "role/pawlocal-${environment}-terraform-apply") &&
      strcontains(policy.minified_json, "role/pawlocal-${environment}-github-deploy") &&
      strcontains(policy.minified_json, "role/pawlocal-${environment}-dsql-runtime") &&
      strcontains(policy.minified_json, "dsql:PutClusterPolicy") &&
      strcontains(policy.minified_json, "lightsail:CreateContainerServiceDeployment") &&
      !strcontains(policy.minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Runtime-stage policy administration, attachments, and mutations must remain fixed to matching environment names and roles."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      !strcontains(policy.minified_json, "cloudfront:CreateDistribution") &&
      !strcontains(policy.minified_json, "cloudfront:CreateOriginAccessControl") &&
      strcontains(policy.minified_json, "cloudfront:UpdateDistribution") &&
      strcontains(policy.minified_json, "cloudfront:UpdateOriginAccessControl")
    ])
    error_message = "The runtime stage must remove broad first-create CloudFront actions after exact handoff ARNs are available."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      !strcontains(policy.minified_json, "dsql:CreateCluster") &&
      !strcontains(policy.minified_json, "dsql:TagResource")
    ])
    error_message = "The runtime boundary must remove DSQL pre-create authorization after the exact cluster ARN is handed off."
  }
}
