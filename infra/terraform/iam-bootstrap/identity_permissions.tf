# Boundaries use stable resource-family ceilings so the first environment
# deployment is not blocked on generated identifiers. Environment-owned
# policies remain exact-resource grants; effective permissions are their
# intersection with these boundaries.
locals {
  identity_environment_resources = {
    for environment in keys(local.environments) : environment => {
      bucket_arn       = "arn:${data.aws_partition.current.partition}:s3:::pawlocal-${environment}-*"
      distribution_arn = "arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"
      cluster_arn      = "arn:${data.aws_partition.current.partition}:dsql:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/*"
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
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = [var.project_name]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = [each.key]
    }
  }
  statement {
    sid       = "AllowApprovedRuntimeDatabaseConnection"
    effect    = "Allow"
    actions   = ["dsql:DbConnect"]
    resources = [each.value.cluster_arn]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = [var.project_name]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = [each.key]
    }
  }
  statement {
    sid       = "ReadOnlyMatchingRuntimeIngestionToken"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/pawlocal/${each.key}/secrets/grafana/otlp-token"]
  }
  dynamic "statement" {
    for_each = contains(keys(var.hosted_telemetry_kms_key_arns), each.key) ? [var.hosted_telemetry_kms_key_arns[each.key]] : []
    content {
      actions   = ["kms:Decrypt"]
      resources = [statement.value]
      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["ssm.${var.aws_region}.amazonaws.com"]
      }
      condition {
        test     = "StringEquals"
        variable = "kms:EncryptionContext:PARAMETER_ARN"
        values   = ["arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/pawlocal/${each.key}/secrets/grafana/otlp-token"]
      }
    }
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

variable "hosted_telemetry_kms_key_arns" {
  description = "Optional exact existing KMS key for the environment runtime ingestion token. No key is created."
  type        = map(string)
  default     = {}
  validation {
    condition     = alltrue([for environment, key in var.hosted_telemetry_kms_key_arns : contains(["development", "production"], environment) && can(regex("^arn:${data.aws_partition.current.partition}:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:key/[0-9a-f-]{36}$", key))])
    error_message = "Runtime token keys must be existing keys in the matching account and region."
  }
}
