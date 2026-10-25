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
  values = { account_id = "111111111111" }
}

override_data {
  target = data.aws_partition.current
  values = { partition = "aws" }
}

variables {
  terraform_state_bucket_name = "fixture-state-bucket-x"
  github_repository           = "example/pawlocal"
  github_owner_id             = "1"
  github_repository_id        = "2"
  manage_github_oidc_provider = true
  route53_zone_id             = "ZFIXTURE000000"
  domain_name                 = "fixture.example"
}

run "permanent_dns_deletion_is_apply_only_namespaced_and_size_safe" {
  command   = plan
  providers = { aws = aws.test }

  assert {
    condition = alltrue([for environment, expected in {
      development = ["api-dev.fixture.example", "pawlocal-dev.fixture.example", "_*.api-dev.fixture.example"]
      production  = ["api.fixture.example", "pawlocal.fixture.example", "_*.api.fixture.example"]
      } : alltrue([for grant in [one([for statement in jsondecode(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json).Statement : statement if try(statement.Sid, "") == "DeleteOnlyEnvironmentDNSRecords"])] :
        grant.Effect == "Allow" &&
        toset(flatten([grant.Action])) == toset(["route53:ChangeResourceRecordSets"]) &&
        toset(flatten([grant.Resource])) == toset(["arn:aws:route53:::hostedzone/ZFIXTURE000000"]) &&
        toset(flatten([grant.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]])) == toset(expected) &&
        toset(flatten([grant.Condition["ForAllValues:StringEquals"]["route53:ChangeResourceRecordSetsActions"]])) == toset(["DELETE"]) &&
        toset(flatten([grant.Condition["ForAllValues:StringEquals"]["route53:ChangeResourceRecordSetsRecordTypes"]])) == toset(["A", "AAAA", "CNAME"]) &&
        alltrue([for suffix in ["NormalizedRecordNames", "RecordTypes", "Actions"] : grant.Condition.Null["route53:ChangeResourceRecordSets${suffix}"] == "false"]) &&
        !strcontains(jsonencode(grant), "ResourceTag")
      ])
    ])
    error_message = "Apply roles permanently delete only supported record types in their own configured DNS namespace; no CREATE/UPSERT, missing-key or unsupported tag condition is permitted."
  }

  assert {
    condition = alltrue([for environment in ["development", "production"] :
      !strcontains(data.aws_iam_policy_document.role_permissions["${environment}-plan"].minified_json, "DeleteOnlyEnvironmentDNSRecords") &&
      !strcontains(data.aws_iam_policy_document.role_permissions["${environment}-plan"].minified_json, "route53:ChangeResourceRecordSets") &&
      # Existing other inline policy is one small AssumeRole statement; reserve
      # 512 bytes (more than its audited size) within the 10240-byte aggregate.
      length(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json) + 512 <= 10240 &&
      anytrue([for statement in jsondecode(data.aws_iam_policy_document.environment_apply_boundary[environment].minified_json).Statement :
        contains(flatten([statement.Action]), "route53:ChangeResourceRecordSets") &&
        try(toset(flatten([statement.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]])) == toset(local.environment_dns_record_names[environment]), false)
      ])
    ])
    error_message = "Plan roles must stay read-only; permanent apply deletion must fit aggregate inline quota and remain inside the matching configured boundary."
  }
}

run "alternate_configuration_is_normalized_and_scoped" {
  command   = plan
  providers = { aws = aws.test }
  variables {
    domain_name     = "  MiXeD.Example.  "
    route53_zone_id = "ZALTERNATE0000"
  }
  assert {
    condition = alltrue([for environment, expected in {
      development = ["api-dev.mixed.example", "pawlocal-dev.mixed.example", "_*.api-dev.mixed.example"]
      production  = ["api.mixed.example", "pawlocal.mixed.example", "_*.api.mixed.example"]
      } : alltrue([for grant in [one([for statement in jsondecode(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json).Statement : statement if try(statement.Sid, "") == "DeleteOnlyEnvironmentDNSRecords"])] :
        toset(flatten([grant.Resource])) == toset(["arn:aws:route53:::hostedzone/ZALTERNATE0000"]) &&
        toset(flatten([grant.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]])) == toset(expected) &&
        !strcontains(jsonencode(grant), "fixture.example") &&
        !strcontains(jsonencode(grant), "ZFIXTURE000000")
      ])
    ])
    error_message = "DNS lifecycle authority must derive normalized names, zone and partition from current configuration rather than retain one deployment's targets."
  }
}

run "resource_policy_deletes_are_apply_only_and_preserve_scope" {
  command   = plan
  providers = { aws = aws.test }
  assert {
    condition = alltrue([for environment in ["development", "production"] :
      alltrue([for grant in [one([for statement in jsondecode(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json).Statement : statement if try(statement.Sid, "") == "DeleteOnlyEnvironmentBucketPolicy"])] :
        toset(flatten([grant.Action])) == toset(["s3:DeleteBucketPolicy"]) &&
        toset(flatten([grant.Resource])) == toset(["arn:aws:s3:::pawlocal-${environment}-*"]) &&
        try(length(grant.Condition), 0) == 0
      ]) &&
      alltrue([for grant in [one([for statement in jsondecode(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json).Statement : statement if try(statement.Sid, "") == "DeleteOnlyTaggedEnvironmentClusterPolicy"])] :
        toset(flatten([grant.Action])) == toset(["dsql:DeleteClusterPolicy"]) &&
        toset(flatten([grant.Resource])) == toset(["arn:aws:dsql:ap-southeast-2:111111111111:cluster/*"]) &&
        grant.Condition.StringEquals["aws:ResourceTag/project"] == var.project_name &&
        grant.Condition.StringEquals["aws:ResourceTag/environment"] == environment
      ]) &&
      !strcontains(data.aws_iam_policy_document.role_permissions["${environment}-plan"].minified_json, "s3:DeleteBucketPolicy") &&
      !strcontains(data.aws_iam_policy_document.role_permissions["${environment}-plan"].minified_json, "dsql:DeleteClusterPolicy") &&
      length(data.aws_iam_policy_document.role_permissions["${environment}-apply"].minified_json) + 512 <= 10240 &&
      length(data.aws_iam_policy_document.environment_apply_boundary[environment].minified_json) <= 6100
    ])
    error_message = "The exact missing S3/DSQL provider deletes must be independently available only to apply roles within existing environment ownership and policy-size limits."
  }
}
