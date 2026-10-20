# The identity state is applied after the environment foundation exposes its
# immutable resource ARNs. Until then, each managed policy grants only access
# to a deliberately nonexistent sentinel ARN.
locals {
  identity_pending_bucket_arn       = "arn:aws:s3:::__pawlocal_identity_scope_pending__"
  identity_pending_distribution_arn = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/PENDING"
  identity_pending_cluster_arn      = "arn:aws:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/PENDING"

  identity_development_bucket_arn       = var.development_frontend_bucket_arn != "" ? var.development_frontend_bucket_arn : local.identity_pending_bucket_arn
  identity_production_bucket_arn        = var.production_frontend_bucket_arn != "" ? var.production_frontend_bucket_arn : local.identity_pending_bucket_arn
  identity_development_distribution_arn = var.development_distribution_arn != "" ? var.development_distribution_arn : local.identity_pending_distribution_arn
  identity_production_distribution_arn  = var.production_distribution_arn != "" ? var.production_distribution_arn : local.identity_pending_distribution_arn
  identity_development_cluster_arn      = var.development_dsql_cluster_arn != "" ? var.development_dsql_cluster_arn : local.identity_pending_cluster_arn
  identity_production_cluster_arn       = var.production_dsql_cluster_arn != "" ? var.production_dsql_cluster_arn : local.identity_pending_cluster_arn
  identity_environment_resources = {
    development = {
      bucket_arn       = local.identity_development_bucket_arn
      distribution_arn = local.identity_development_distribution_arn
      cluster_arn      = local.identity_development_cluster_arn
    }
    production = {
      bucket_arn       = local.identity_production_bucket_arn
      distribution_arn = local.identity_production_distribution_arn
      cluster_arn      = local.identity_production_cluster_arn
    }
  }
}

resource "aws_iam_service_linked_role" "dsql" {
  aws_service_name = "dsql.amazonaws.com"
  description      = "Service-linked role used by Aurora DSQL to create and manage its AWS resources."

  lifecycle {
    ignore_changes = [description]
  }
}

import {
  for_each = var.import_existing_dsql_service_linked_role ? {
    existing = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/dsql.amazonaws.com/AWSServiceRoleForAuroraDsql"
  } : {}
  to = aws_iam_service_linked_role.dsql
  id = each.value
}

output "dsql_service_linked_role_arn" {
  description = "Terraform-managed Aurora DSQL service-linked role required before creating clusters."
  value       = aws_iam_service_linked_role.dsql.arn
}

data "aws_iam_policy_document" "identity_development_frontend" {
  statement {
    sid       = "ListDevelopmentFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.identity_development_bucket_arn]
  }
  statement {
    sid       = "PublishDevelopmentFrontendObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.identity_development_bucket_arn}/*"]
  }
  statement {
    sid       = "InvalidateDevelopmentDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [local.identity_development_distribution_arn]
  }
}

data "aws_iam_policy_document" "identity_production_frontend" {
  statement {
    sid       = "ListProductionFrontendBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.identity_production_bucket_arn]
  }
  statement {
    sid       = "PublishProductionFrontendObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.identity_production_bucket_arn}/*"]
  }
  statement {
    sid       = "InvalidateProductionDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [local.identity_production_distribution_arn]
  }
}

data "aws_iam_policy_document" "identity_development_runtime" {
  statement {
    sid       = "ConnectOnlyToDevelopmentDSQL"
    effect    = "Allow"
    actions   = ["dsql:DbConnect"]
    resources = [local.identity_development_cluster_arn]
  }
}

data "aws_iam_policy_document" "identity_production_runtime" {
  statement {
    sid       = "ConnectOnlyToProductionDSQL"
    effect    = "Allow"
    actions   = ["dsql:DbConnect"]
    resources = [local.identity_production_cluster_arn]
  }
}

data "aws_iam_policy_document" "identity_app_role_boundary" {
  for_each = local.identity_environment_resources

  statement {
    sid       = "AllowApprovedFrontendPublishActions"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [each.value.bucket_arn]
  }
  statement {
    sid       = "AllowApprovedFrontendObjectActions"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${each.value.bucket_arn}/*"]
  }
  statement {
    sid       = "AllowApprovedFrontendInvalidations"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [each.value.distribution_arn]
  }
  statement {
    sid       = "AllowApprovedRuntimeDatabaseConnection"
    effect    = "Allow"
    actions   = ["dsql:DbConnect"]
    resources = [each.value.cluster_arn]
  }
}

resource "aws_iam_policy" "identity_development_frontend" {
  name        = "pawlocal-identity-development-frontend-publish"
  description = "Fixed least-privilege frontend publishing policy for PawLocal development."
  policy      = data.aws_iam_policy_document.identity_development_frontend.json
}

resource "aws_iam_policy" "identity_production_frontend" {
  name        = "pawlocal-identity-production-frontend-publish"
  description = "Fixed least-privilege frontend publishing policy for PawLocal production."
  policy      = data.aws_iam_policy_document.identity_production_frontend.json
}

resource "aws_iam_policy" "identity_development_runtime" {
  name        = "pawlocal-identity-development-dsql-connect"
  description = "Fixed least-privilege Aurora DSQL connection policy for PawLocal development runtime."
  policy      = data.aws_iam_policy_document.identity_development_runtime.json
}

resource "aws_iam_policy" "identity_production_runtime" {
  name        = "pawlocal-identity-production-dsql-connect"
  description = "Fixed least-privilege Aurora DSQL connection policy for PawLocal production runtime."
  policy      = data.aws_iam_policy_document.identity_production_runtime.json
}

resource "aws_iam_policy" "identity_app_role_boundary" {
  for_each = local.identity_environment_resources

  name        = each.key == "development" ? "pawlocal-app-role-boundary" : "pawlocal-${each.key}-app-role-boundary"
  description = "Permissions ceiling for fixed PawLocal ${each.key} publisher and runtime identity roles."
  policy      = data.aws_iam_policy_document.identity_app_role_boundary[each.key].json
}

moved {
  from = aws_iam_policy.identity_app_role_boundary
  to   = aws_iam_policy.identity_app_role_boundary["development"]
}
