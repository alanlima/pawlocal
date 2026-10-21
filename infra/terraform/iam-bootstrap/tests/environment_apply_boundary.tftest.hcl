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
    # Synthetic values match the production input lengths that render the
    # largest reviewed boundary without exposing live identifiers.
    terraform_state_bucket_name = "fixture-state-bucket-x"
    github_repository           = "example/pawlocal"
    github_owner_id             = "1"
    github_repository_id        = "2"
    manage_github_oidc_provider = true
    route53_zone_id             = "ZFIXTURE000000"
    domain_name                 = "fixture.example"
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      length(policy.minified_json) < 6144 &&
      length(policy.minified_json) <= local.environment_apply_boundary_max_bytes
    ])
    error_message = "Each minified environment apply boundary must stay below both the 6144-byte AWS limit and the 6060-byte repository budget."
  }

  assert {
    condition     = length(data.aws_iam_policy_document.environment_apply_boundary["development"].minified_json) == 5973
    error_message = "The real-input-equivalent development fixture must retain the reviewed 5973-byte boundary shape."
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
      strcontains(policy.minified_json, "policy/pawlocal-${environment}-*") &&
      strcontains(policy.minified_json, "role/pawlocal-${environment}-*") &&
      !strcontains(policy.minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Stable policy administration and attachment ceilings must stay limited to matching environment name prefixes."
  }

  assert {
    condition = alltrue([
      for environment in keys(local.environments) :
      alltrue([
        for policy_arn in local.environment_application_policy_arns[environment] :
        strcontains(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json, policy_arn)
      ]) &&
      strcontains(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json, "role/pawlocal-${environment}-terraform-apply") &&
      strcontains(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json, "role/pawlocal-${environment}-github-deploy") &&
      strcontains(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json, "role/pawlocal-${environment}-dsql-runtime") &&
      !strcontains(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Each apply role's identity policy must remain the exact matching-environment subset of the stable boundary ceiling."
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
      strcontains(policy.minified_json, "s3:PutBucketPublicAccessBlock") &&
      !strcontains(policy.minified_json, "s3:PutPublicAccessBlock") &&
      strcontains(policy.minified_json, "s3:GetBucket*") &&
      strcontains(policy.minified_json, "s3:Get*Configuration") &&
      !strcontains(policy.minified_json, "\"s3:Get*\"") &&
      strcontains(policy.minified_json, "aws:TagKeys") &&
      strcontains(policy.minified_json, "dsql:TagResource") &&
      strcontains(policy.minified_json, "cloudfront:CreateDistribution") &&
      strcontains(policy.minified_json, "cloudfront:TagResource") &&
      strcontains(policy.minified_json, "cloudfront:CreateOriginAccessControl") &&
      strcontains(policy.minified_json, "cloudfront:*Function") &&
      strcontains(policy.minified_json, "cloudfront:Get*") &&
      strcontains(policy.minified_json, "cloudfront:List*")
    ])
    error_message = "Tagged create dependencies, name-scoped S3 pre-tag reads, and the initial CloudFront handoff must remain available without a broad s3:Get* grant."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "cloudfront:DeleteDistribution") &&
      strcontains(policy.minified_json, "cloudfront:UpdateDistribution") &&
      strcontains(policy.minified_json, "cloudfront:DeleteOriginAccessControl") &&
      strcontains(policy.minified_json, "cloudfront:UpdateOriginAccessControl")
    ])
    error_message = "Stable boundaries must contain the post-create CloudFront ceilings before generated identifiers exist."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "s3:PutBucketOwnershipControls") &&
        contains(flatten([statement.Action]), "s3:PutBucketPublicAccessBlock") &&
        !contains(keys(statement), "Condition")
      ]) == 1
    ])
    error_message = "Immediate post-create S3 configuration must be admitted by the generated matching environment bucket name without a resource-tag propagation dependency."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      alltrue([
        for statement in jsondecode(policy.minified_json).Statement :
        try(
          !contains(keys(statement.Condition), "Null") &&
          statement.Condition.StringEquals["aws:ResourceTag/project"] == "pawlocal" &&
          statement.Condition.StringEquals["aws:ResourceTag/environment"] != "",
          true
        )
        if length(setintersection(toset(flatten([statement.Action])), toset([
          "cloudfront:TagResource", "cognito-idp:TagResource", "dsql:TagResource", "lightsail:TagResource"
        ]))) > 0
      ])
    ])
    error_message = "Create-time dependent TagResource boundary statements must match surfaced authorization tags without requiring them to be absent."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "lightsail:TagResource") &&
        contains(flatten([statement.Resource]), "arn:aws:lightsail:ap-southeast-2:111111111111:ContainerService/*")
      ]) == 1
    ])
    error_message = "Each boundary must admit Lightsail's pre-creation ContainerService/* TagResource authorization."
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

  assert {
    condition = alltrue([
      for role in ["development-plan", "development-apply", "production-plan", "production-apply"] :
      contains(flatten([
        for statement in jsondecode(data.aws_iam_policy_document.role_permissions[role].json).Statement :
        flatten([statement.Action])
      ]), "lightsail:GetOperation")
    ])
    error_message = "Every environment Terraform role must be able to read the singular Lightsail operation polled by provider waiters."
  }
}

run "stable_boundaries_cover_pre_and_post_deploy" {
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
    error_message = "Each stable apply boundary must stay below both the 6144-byte AWS limit and the repository budget."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "policy/pawlocal-${environment}-*") &&
      strcontains(policy.minified_json, "role/pawlocal-${environment}-*") &&
      strcontains(policy.minified_json, "dsql:PutClusterPolicy") &&
      strcontains(policy.minified_json, "lightsail:CreateContainerServiceDeployment") &&
      !strcontains(policy.minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Stable policy administration, attachment ceilings, and mutations must remain fixed to matching environment name prefixes and tags."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "cloudfront:CreateDistribution") &&
      strcontains(policy.minified_json, "cloudfront:CreateOriginAccessControl") &&
      strcontains(policy.minified_json, "cloudfront:UpdateDistribution") &&
      strcontains(policy.minified_json, "cloudfront:UpdateOriginAccessControl")
    ])
    error_message = "Stable boundaries must cover both create-time and post-create CloudFront operations."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "cloudfront:DeleteDistribution") &&
        contains(flatten([statement.Action]), "cloudfront:UpdateDistribution") &&
        !contains(flatten([statement.Action]), "cloudfront:DeleteOriginAccessControl") &&
        !contains(flatten([statement.Action]), "cloudfront:UpdateOriginAccessControl") &&
        toset(flatten([statement.Resource])) == toset(["arn:aws:cloudfront::111111111111:distribution/*"]) &&
        statement.Condition.StringEquals["aws:ResourceTag/project"] == "pawlocal" &&
        statement.Condition.StringEquals["aws:ResourceTag/environment"] == environment
      ]) == 1
    ])
    error_message = "Distribution update/delete actions must use the account resource family with matching project/environment tags."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      length([
        for statement in jsondecode(policy.minified_json).Statement : statement
        if contains(flatten([statement.Action]), "cloudfront:DeleteOriginAccessControl") &&
        contains(flatten([statement.Action]), "cloudfront:UpdateOriginAccessControl") &&
        !contains(flatten([statement.Action]), "cloudfront:DeleteDistribution") &&
        !contains(flatten([statement.Action]), "cloudfront:UpdateDistribution") &&
        toset(flatten([statement.Resource])) == toset(["arn:aws:cloudfront::111111111111:origin-access-control/*"])
      ]) == 1
    ])
    error_message = "OAC update/delete actions must stay in a separate account resource-family statement."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "pawlocal-${environment}-") &&
      !strcontains(policy.minified_json, "pawlocal-${environment == "development" ? "production" : "development"}-")
    ])
    error_message = "Name-representable resources must remain isolated to the matching environment."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.environment_apply_boundary :
      strcontains(policy.minified_json, "dsql:CreateCluster") &&
      strcontains(policy.minified_json, "dsql:TagResource")
    ])
    error_message = "Stable boundaries must retain tag-constrained DSQL creation without a generated cluster handoff."
  }
}

run "stable_app_role_boundaries_require_exact_environment_policies" {
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
    condition     = toset(keys(data.aws_iam_policy_document.identity_app_role_boundary)) == toset(["development", "production"])
    error_message = "Unknown environments must not receive an app-role boundary."
  }

  assert {
    condition = alltrue([
      for environment, policy in data.aws_iam_policy_document.identity_app_role_boundary :
      strcontains(policy.minified_json, "arn:aws:s3:::pawlocal-${environment}-*") &&
      strcontains(policy.minified_json, "arn:aws:cloudfront::111111111111:distribution/*") &&
      strcontains(policy.minified_json, "arn:aws:dsql:ap-southeast-2:111111111111:cluster/*") &&
      strcontains(policy.minified_json, "aws:ResourceTag/project") &&
      strcontains(policy.minified_json, "aws:ResourceTag/environment") &&
      strcontains(policy.minified_json, environment) &&
      !strcontains(policy.minified_json, "PENDING") &&
      !strcontains(policy.minified_json, "__pawlocal_identity_scope_pending__")
    ])
    error_message = "App-role boundaries must use stable name/tag-scoped resource families without sentinel identifiers."
  }

  assert {
    condition = alltrue([
      for policy in data.aws_iam_policy_document.identity_app_role_boundary :
      length(policy.minified_json) < 6144
    ])
    error_message = "Each stable app-role boundary must stay below IAM's managed-policy size limit."
  }
}
