# The identity state is applied after the environment foundation exposes its
# immutable resource ARNs. Until then, each boundary grants only access to a
# deliberately nonexistent sentinel ARN.
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
  identity_app_role_boundary_descriptions = {
    development = "Permissions ceiling for the three fixed PawLocal app identity roles."
    production  = "Permissions ceiling for fixed PawLocal production publisher and runtime identity roles."
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

removed {
  from = aws_iam_policy.identity_development_frontend

  lifecycle {
    destroy = true
  }
}

removed {
  from = aws_iam_policy.identity_production_frontend

  lifecycle {
    destroy = true
  }
}

removed {
  from = aws_iam_policy.identity_development_runtime

  lifecycle {
    destroy = true
  }
}

removed {
  from = aws_iam_policy.identity_production_runtime

  lifecycle {
    destroy = true
  }
}

resource "aws_iam_policy" "identity_app_role_boundary" {
  for_each = local.identity_environment_resources

  name        = each.key == "development" ? "pawlocal-app-role-boundary" : "pawlocal-${each.key}-app-role-boundary"
  description = local.identity_app_role_boundary_descriptions[each.key]
  policy      = data.aws_iam_policy_document.identity_app_role_boundary[each.key].json
}

moved {
  from = aws_iam_policy.identity_app_role_boundary
  to   = aws_iam_policy.identity_app_role_boundary["development"]
}
