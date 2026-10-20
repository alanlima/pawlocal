# Recovery mutation grants are disabled by default. Enabling them requires the
# exact, reviewed legacy inventory; no AWS resource IDs are inferred here.
variable "enable_legacy_recovery_destroy" {
  description = "Enable exact-inventory legacy destroy grants after the complete inventory is reviewed."
  type        = bool
  default     = false
}

variable "legacy_recovery_resource_arns" {
  description = "Exact resource ARNs and DNS names from the reviewed legacy destroy plan. Leave empty until that inventory is known."
  type = object({
    frontend_buckets             = list(string)
    cloudfront_distributions     = list(string)
    cloudfront_origin_controls   = list(string)
    cloudfront_functions         = list(string)
    dsql_clusters                = list(string)
    lightsail_container_services = list(string)
    lightsail_certificates       = list(string)
    cognito_user_pools           = list(string)
    route53_record_names         = list(string)
  })
  default = {
    frontend_buckets             = []
    cloudfront_distributions     = []
    cloudfront_origin_controls   = []
    cloudfront_functions         = []
    dsql_clusters                = []
    lightsail_container_services = []
    lightsail_certificates       = []
    cognito_user_pools           = []
    route53_record_names         = []
  }
  validation {
    condition = alltrue(flatten([
      for arns in [
        var.legacy_recovery_resource_arns.frontend_buckets,
        var.legacy_recovery_resource_arns.cloudfront_distributions,
        var.legacy_recovery_resource_arns.cloudfront_origin_controls,
        var.legacy_recovery_resource_arns.cloudfront_functions,
        var.legacy_recovery_resource_arns.dsql_clusters,
        var.legacy_recovery_resource_arns.lightsail_container_services,
        var.legacy_recovery_resource_arns.lightsail_certificates,
        var.legacy_recovery_resource_arns.cognito_user_pools
      ] : [for arn in arns : startswith(arn, "arn:") && !strcontains(arn, "*") && !strcontains(arn, "?")]
    ]))
    error_message = "Recovery service inventory must use exact ARNs without wildcard characters."
  }
  validation {
    condition = alltrue([
      length(distinct(var.legacy_recovery_resource_arns.frontend_buckets)) == length(var.legacy_recovery_resource_arns.frontend_buckets),
      length(distinct(var.legacy_recovery_resource_arns.cloudfront_distributions)) == length(var.legacy_recovery_resource_arns.cloudfront_distributions),
      length(distinct(var.legacy_recovery_resource_arns.cloudfront_origin_controls)) == length(var.legacy_recovery_resource_arns.cloudfront_origin_controls),
      length(distinct(var.legacy_recovery_resource_arns.dsql_clusters)) == length(var.legacy_recovery_resource_arns.dsql_clusters),
      length(distinct(var.legacy_recovery_resource_arns.lightsail_container_services)) == length(var.legacy_recovery_resource_arns.lightsail_container_services),
      length(distinct(var.legacy_recovery_resource_arns.lightsail_certificates)) == length(var.legacy_recovery_resource_arns.lightsail_certificates),
      length(distinct(var.legacy_recovery_resource_arns.cognito_user_pools)) == length(var.legacy_recovery_resource_arns.cognito_user_pools),
      length(distinct(var.legacy_recovery_resource_arns.route53_record_names)) == length(var.legacy_recovery_resource_arns.route53_record_names)
    ])
    error_message = "Recovery inventory entries must be distinct; duplicate ARNs or DNS names are not accepted."
  }
  validation {
    condition = alltrue([
      for arn in var.legacy_recovery_resource_arns.frontend_buckets : can(regex("^arn:[^:]+:s3:::pawlocal-(frontend-[0-9a-f]{8}|development-[0-9a-f]{6}|production-[0-9a-f]{6})$", arn))
      ]) && alltrue([
      for arn in var.legacy_recovery_resource_arns.cloudfront_distributions : can(regex("^arn:[^:]+:cloudfront::[0-9]{12}:distribution/[A-Z0-9]+$", arn))
      ]) && alltrue([
      for arn in var.legacy_recovery_resource_arns.cloudfront_origin_controls : can(regex("^arn:[^:]+:cloudfront::[0-9]{12}:origin-access-control/[A-Za-z0-9]+$", arn))
      ]) && alltrue([
      for arn in var.legacy_recovery_resource_arns.cloudfront_functions : can(regex("^arn:[^:]+:cloudfront::[0-9]{12}:function/pawlocal-(development|production)-spa-routing$", arn))
      ]) && alltrue([
      for arn in var.legacy_recovery_resource_arns.dsql_clusters : can(regex("^arn:[^:]+:dsql:[a-z0-9-]+:[0-9]{12}:cluster/[A-Za-z0-9-]+$", arn))
      ]) && alltrue([
      for arn in var.legacy_recovery_resource_arns.lightsail_container_services : can(regex("^arn:[^:]+:lightsail:[a-z0-9-]+:[0-9]{12}:ContainerService/pawlocal-(development|production)-api$", arn))
      ]) && alltrue([
      for arn in var.legacy_recovery_resource_arns.lightsail_certificates : can(regex("^arn:[^:]+:lightsail:[a-z0-9-]+:[0-9]{12}:Certificate/pawlocal-(development|production)-api-migration-20261019$", arn))
      ]) && alltrue([
      for arn in var.legacy_recovery_resource_arns.cognito_user_pools : can(regex("^arn:[^:]+:cognito-idp:[a-z0-9-]+:[0-9]{12}:userpool/[a-z0-9-]+_[A-Za-z0-9]+$", arn))
    ])
    error_message = "Recovery ARNs must match the resource types and PawLocal names in the tracked legacy root."
  }
  validation {
    condition = alltrue([
      for name in var.legacy_recovery_resource_arns.route53_record_names :
      name == lower(name) && !strcontains(name, "*") && !strcontains(name, "?") && endswith(name, ".${trimsuffix(var.domain_name, ".")}")
    ])
    error_message = "Recovery DNS names must be exact lowercase names under the configured domain."
  }
  validation {
    condition = !var.enable_legacy_recovery_destroy || (
      length(var.legacy_recovery_resource_arns.frontend_buckets) == 3 &&
      length(var.legacy_recovery_resource_arns.cloudfront_distributions) == 3 &&
      length(var.legacy_recovery_resource_arns.cloudfront_origin_controls) == 3 &&
      length(var.legacy_recovery_resource_arns.cloudfront_functions) == 3 &&
      length(var.legacy_recovery_resource_arns.dsql_clusters) == 2 &&
      length(var.legacy_recovery_resource_arns.lightsail_container_services) == 2 &&
      length(var.legacy_recovery_resource_arns.lightsail_certificates) == 2 &&
      length(var.legacy_recovery_resource_arns.cognito_user_pools) == 2 &&
      length(var.legacy_recovery_resource_arns.route53_record_names) == 6
    )
    error_message = "Destroy grants require the complete tracked inventory: three frontend buckets/CDNs/OACs/functions; two each DSQL, Lightsail services/certificates, Cognito pools; and six DNS record names."
  }
}

variable "legacy_recovery_dsql_cluster_arns" {
  description = "Exact legacy DSQL cluster ARNs for the isolated deletion-protection apply role. Empty until known."
  type        = list(string)
  default     = []
  validation {
    condition = length(var.legacy_recovery_dsql_cluster_arns) == 0 || (
      length(var.legacy_recovery_dsql_cluster_arns) == 2 &&
      length(distinct(var.legacy_recovery_dsql_cluster_arns)) == 2 &&
      alltrue([for arn in var.legacy_recovery_dsql_cluster_arns : startswith(arn, "arn:") && !strcontains(arn, "*") && !strcontains(arn, "?")])
    )
    error_message = "Set either no DSQL recovery ARNs or exactly two exact cluster ARNs without wildcards."
  }
}

data "aws_iam_policy_document" "recovery_dsql_protection_apply" {
  count = length(var.legacy_recovery_dsql_cluster_arns) == 2 ? 1 : 0
  statement {
    sid       = "DisableProtectionOnExactLegacyDSQLClusters"
    effect    = "Allow"
    actions   = ["dsql:UpdateCluster"]
    resources = var.legacy_recovery_dsql_cluster_arns
  }
}

resource "aws_iam_role_policy" "recovery_dsql_protection_apply" {
  count  = length(var.legacy_recovery_dsql_cluster_arns) == 2 ? 1 : 0
  name   = "pawlocal-recovery-dsql-protection"
  role   = aws_iam_role.github_terraform["recovery-dsql-protection-apply"].id
  policy = data.aws_iam_policy_document.recovery_dsql_protection_apply[0].json
  lifecycle {
    precondition {
      condition = alltrue([
        for arn in var.legacy_recovery_dsql_cluster_arns : can(regex("^arn:${data.aws_partition.current.partition}:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/[A-Za-z0-9-]+$", arn))
      ])
      error_message = "DSQL recovery grants must target exact clusters in the configured account and region."
    }
  }
}

resource "aws_iam_role_policy" "recovery_oac_read" {
  for_each = {
    for key, role in local.role_definitions : key => role
    if role.environment == "recovery" && key != "recovery-dsql-protection-apply" && length(var.legacy_recovery_resource_arns.cloudfront_origin_controls) > 0
  }
  name = "pawlocal-recovery-exact-oac-read"
  role = aws_iam_role.github_terraform[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadExactLegacyRecoveryOACs"
      Effect   = "Allow"
      Action   = ["cloudfront:GetOriginAccessControl", "cloudfront:GetOriginAccessControlConfig"]
      Resource = var.legacy_recovery_resource_arns.cloudfront_origin_controls
    }]
  })
}

data "aws_iam_policy_document" "legacy_recovery_destroy" {
  count = var.enable_legacy_recovery_destroy ? 1 : 0

  statement {
    sid    = "EmptyAndDeleteExactLegacyFrontendBuckets"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload", "s3:DeleteBucket", "s3:DeleteBucketPolicy",
      "s3:DeleteObject", "s3:DeleteObjectVersion", "s3:ListBucket", "s3:ListBucketMultipartUploads",
      "s3:ListBucketVersions", "s3:PutBucketOwnershipControls", "s3:PutBucketPublicAccessBlock",
      "s3:PutEncryptionConfiguration"
    ]
    resources = concat(
      var.legacy_recovery_resource_arns.frontend_buckets,
      [for arn in var.legacy_recovery_resource_arns.frontend_buckets : "${arn}/*"]
    )
  }
  statement {
    sid       = "DisableAndDeleteExactLegacyCloudFrontDistributions"
    effect    = "Allow"
    actions   = ["cloudfront:DeleteDistribution", "cloudfront:UpdateDistribution"]
    resources = var.legacy_recovery_resource_arns.cloudfront_distributions
  }
  statement {
    sid       = "DeleteExactLegacyCloudFrontOriginsAndFunctions"
    effect    = "Allow"
    actions   = ["cloudfront:DeleteFunction", "cloudfront:DeleteOriginAccessControl"]
    resources = concat(var.legacy_recovery_resource_arns.cloudfront_functions, var.legacy_recovery_resource_arns.cloudfront_origin_controls)
  }
  statement {
    sid       = "DeleteExactLegacyDSQLClustersAndPolicies"
    effect    = "Allow"
    actions   = ["dsql:DeleteCluster", "dsql:DeleteClusterPolicy"]
    resources = var.legacy_recovery_resource_arns.dsql_clusters
  }
  statement {
    sid       = "DeleteExactLegacyLightsailResources"
    effect    = "Allow"
    actions   = ["lightsail:DeleteCertificate", "lightsail:DeleteContainerService"]
    resources = concat(var.legacy_recovery_resource_arns.lightsail_certificates, var.legacy_recovery_resource_arns.lightsail_container_services)
  }
  statement {
    sid       = "DeleteExactLegacyCognitoPoolsAndClients"
    effect    = "Allow"
    actions   = ["cognito-idp:DeleteUserPool", "cognito-idp:DeleteUserPoolClient", "cognito-idp:DeleteUserPoolDomain"]
    resources = var.legacy_recovery_resource_arns.cognito_user_pools
  }
  statement {
    sid       = "DeleteOnlyReviewedLegacyDNSRecords"
    effect    = "Allow"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = ["arn:aws:route53:::hostedzone/${var.route53_zone_id}"]
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsActions"
      values   = ["DELETE"]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
      values   = var.legacy_recovery_resource_arns.route53_record_names
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsRecordTypes"
      values   = ["A", "AAAA", "CNAME"]
    }
  }
  statement {
    sid    = "DeleteExactLegacyApplicationIAMRolesAndPolicies"
    effect = "Allow"
    actions = [
      "iam:DeleteRole", "iam:DeleteRolePolicy", "iam:GetRole", "iam:GetRolePolicy",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies"
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-frontend-github-deploy",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-github-deploy",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-github-deploy",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-terraform-deploy",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-production-terraform-deploy",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/pawlocal-development-dsql-runtime"
    ]
  }
  statement {
    sid       = "DeleteOnlyTheLegacyPawLocalOIDCProvider"
    effect    = "Allow"
    actions   = ["iam:DeleteOpenIDConnectProvider"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"]
  }
}

resource "aws_iam_role_policy" "legacy_recovery_destroy" {
  count  = var.enable_legacy_recovery_destroy ? 1 : 0
  name   = "pawlocal-legacy-recovery-destroy"
  role   = aws_iam_role.github_terraform["recovery-apply"].id
  policy = data.aws_iam_policy_document.legacy_recovery_destroy[0].json
  lifecycle {
    precondition {
      condition = alltrue(flatten([
        for arns in [
          var.legacy_recovery_resource_arns.cloudfront_distributions,
          var.legacy_recovery_resource_arns.cloudfront_origin_controls,
          var.legacy_recovery_resource_arns.cloudfront_functions,
          var.legacy_recovery_resource_arns.dsql_clusters,
          var.legacy_recovery_resource_arns.lightsail_container_services,
          var.legacy_recovery_resource_arns.lightsail_certificates,
          var.legacy_recovery_resource_arns.cognito_user_pools
        ] : [for arn in arns : can(regex("^arn:${data.aws_partition.current.partition}:[^:]+:[^:]*:${data.aws_caller_identity.current.account_id}:", arn))]
        ])) && alltrue(flatten([
        for arns in [
          var.legacy_recovery_resource_arns.dsql_clusters,
          var.legacy_recovery_resource_arns.lightsail_container_services,
          var.legacy_recovery_resource_arns.lightsail_certificates,
          var.legacy_recovery_resource_arns.cognito_user_pools
        ] : [for arn in arns : can(regex("^arn:${data.aws_partition.current.partition}:[^:]+:${var.aws_region}:${data.aws_caller_identity.current.account_id}:", arn))]
      ]))
      error_message = "Every service ARN must belong to the current AWS account and partition."
    }
  }
}
