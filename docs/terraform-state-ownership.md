# Terraform state ownership and migration

This runbook implements [Issue #81](https://github.com/alanlima/pawlocal/issues/81) and [DEC-008](decisions.md#dec-008--separate-shared-and-application-terraform-ownership). It describes a future, reviewed state migration. This PR does not apply it, write remote state, or mutate AWS resources.

## Roots and dependencies

| Root | State key after migration | Ownership |
|---|---|---|
| `infra/terraform` | Existing `pawlocal/terraform.tfstate` during migration only | Forget-only source; all prior resource declarations are represented by `removed` blocks with `destroy = false`. Do not use it for routine plans/deployments after migration. |
| `infra/terraform/app-infra` | `pawlocal/app-infra.tfstate` | Existing production frontend resources and all application resources formerly under `module.fullstack`, including dev/prod container deployments, DSQL, Cognito, DNS, and dev frontend. |
| `infra/terraform/shared-infra` | `pawlocal/shared-infra.tfstate` | Existing GitHub OIDC provider and publisher/Terraform deployment roles and policies. Reads exact target ARNs from the app root's `shared_iam_targets` output. |

Dependency order is **old root -> app-infra -> shared-infra**. App configuration does not consume shared-state outputs, so it can be imported first. Shared policies require app outputs and must not be planned/imported before app state exists. Artifact uploads remain separate from infrastructure ownership; the release Terraform role changes only the selected Lightsail deployment-version resource.

## Resource address inventory

All addresses below retain the current provider configuration and resource identities. Bracketed keys are Terraform instance keys. Root and module resources keep their existing addresses in `app-infra`; the only address renames are the three development publisher addresses shown in the shared table.

### Application root addresses retained in `app-infra`

| Current address | Destination address |
|---|---|
| `random_id.site_bucket_suffix` | `random_id.site_bucket_suffix` |
| `aws_s3_bucket.site` | `aws_s3_bucket.site` |
| `aws_s3_bucket_ownership_controls.site` | same |
| `aws_s3_bucket_public_access_block.site` | same |
| `aws_s3_bucket_server_side_encryption_configuration.site` | same |
| `aws_cloudfront_origin_access_control.site` | same |
| `aws_cloudfront_distribution.site` | same |
| `aws_cloudfront_function.site_spa` | same |
| `aws_s3_bucket_policy.site` | same |
| `aws_route53_record.site_a` | same |
| `aws_route53_record.site_aaaa` | same |

### Application child-module addresses retained in `app-infra`

Every source address under `module.fullstack` retains that module path in the app state. Resource families are listed by Terraform type/name and their existing environment/count keys; the state snapshot contains 46 application instances across these blocks.

| Existing resource address family | Existing keys |
|---|---|
| `random_id.bucket_suffix` | `development` |
| `aws_s3_bucket.frontend`, `aws_s3_bucket_ownership_controls.frontend`, `aws_s3_bucket_public_access_block.frontend`, `aws_s3_bucket_server_side_encryption_configuration.frontend`, `aws_s3_bucket_policy.frontend` | `development` |
| `aws_cloudfront_origin_access_control.frontend`, `aws_cloudfront_distribution.app`, `aws_cloudfront_function.spa` | `development` |
| `aws_route53_record.frontend_a`, `aws_route53_record.frontend_aaaa` | `development` |
| `aws_dsql_cluster.app`, `aws_dsql_cluster_policy.api_connect` | `development`, `production` |
| `aws_lightsail_certificate.api`, `aws_lightsail_container_service.api`, `aws_lightsail_container_service_deployment_version.api` | `development`, `production` |
| `aws_route53_record.api_certificate_validation`, `aws_route53_record.api` | `development`, `production` |
| `random_id.cognito_domain_suffix`, `aws_cognito_user_pool.app`, `aws_cognito_user_pool_domain.app`, `aws_cognito_user_pool_client.app` | `development`, `production` |
| `terraform_data.app_dsql_role` | `development`, `production` |
| `aws_s3_bucket.cloudtrail`, `aws_s3_bucket_lifecycle_configuration.cloudtrail`, `aws_s3_bucket_public_access_block.cloudtrail`, `aws_s3_bucket_server_side_encryption_configuration.cloudtrail`, `aws_s3_bucket_policy.cloudtrail`, `aws_cloudtrail.dsql_auth`, `aws_cloudwatch_event_rule.dsql_auth`, `aws_sns_topic.dsql_auth`, `aws_sns_topic_subscription.dsql_auth_email`, `aws_cloudwatch_event_target.dsql_auth`, `aws_sns_topic_policy.dsql_auth` | Existing optional instances only; the authoritative snapshot controls whether any are present. |

Optional counted resources must not be invented during migration. The generated address set must match the authoritative state snapshot exactly.

### Shared IAM addresses

| Current address | Destination address |
|---|---|
| `aws_iam_openid_connect_provider.github[0]` | same |
| `aws_iam_role.github_deploy` | same |
| `aws_iam_role_policy.github_deploy` | same |
| `module.fullstack.aws_iam_role.github_deploy["development"]` | `aws_iam_role.github_deploy_development` |
| `module.fullstack.aws_iam_role_policy.github_deploy["development"]` | `aws_iam_role_policy.github_deploy_development` |
| `module.fullstack.aws_iam_role.github_terraform_deploy["development"]`, `["production"]` | `aws_iam_role.github_terraform_deploy["development"]`, `["production"]` |
| `module.fullstack.aws_iam_role_policy.github_terraform_deploy["development"]`, `["production"]` | `aws_iam_role_policy.github_terraform_deploy["development"]`, `["production"]` |

`module.fullstack.aws_iam_openid_connect_provider.github[0]` is a data source, not a managed state instance. It remains a lookup, so it is not imported.

## Declarative import preparation

Use the same reviewed snapshot and local backend configuration for both generated import files. The generator emits only a count; it does not print state attributes or identifiers. Generated files are ignored by Git because the import IDs are account-specific.

```powershell
$env:PAWLOCAL_TF_STATE_BUCKET = "<existing state bucket>"
Set-Location infra/terraform
terraform init -input=false -backend-config="bucket=$env:PAWLOCAL_TF_STATE_BUCKET" -backend-config="key=pawlocal/terraform.tfstate" -backend-config="region=ap-southeast-2" -backend-config="encrypt=true" -backend-config="use_lockfile=true"
terraform state pull | python ../../ops/generate-terraform-import-blocks.py --layer app --output ../terraform/app-infra/migration-imports.tf
terraform state pull | python ../../ops/generate-terraform-import-blocks.py --layer shared --output ../terraform/shared-infra/migration-imports.tf
```

Review the address-only inventory against this table and the protected state snapshot; do not print or commit the generated IDs. The generator refuses an unexpected managed-address inventory or a resource without a declarative import ID.

## Migration and verification gates

1. Freeze infrastructure plans and releases across all three roots. Confirm the working branch, authoritative state key/serial, issue acceptance, and approved migration window. Save a protected backend-versioned snapshot plus a separate local backup; never add either to Git.
2. Generate/import-check files from that exact snapshot. Run `terraform fmt -check -recursive`, `terraform init`, and `terraform validate` in each root.
3. Plan the old root against the authoritative source state. It must show only forgetting existing addresses via `removed` blocks, with **zero AWS creates, updates, replacements, or destroys**. Save and review the complete plan. Do not apply if any action touches a managed resource.
4. Apply only the reviewed forget-only plan through Terraform after a separately approved migration window. This writes only the old state ownership change; it must not call an AWS resource mutation.
5. Plan `app-infra` using `pawlocal/app-infra.tfstate` and its generated import blocks. Review every import, then verify there are no resource creates, updates, replacements, or destroys after import. Apply the exact reviewed import-only plan; do not change configuration during the operation.
6. Plan `shared-infra` using `pawlocal/shared-infra.tfstate` after app state outputs exist. Review the exact nine shared IAM instances and any policy diff separately; only the expected provider-refresh permission changes may update the IAM inline policies. No other changes are allowed. Apply only after review and explicit approval.
7. Run fresh plans for all roots. They must report no unexpected changes. Verify the old state no longer manages the moved resources, app state owns exactly the app inventory, shared state owns exactly nine IAM instances, and shared outputs match app targets. Keep the old state key/version as recovery evidence; do not delete the old backend.
8. Only after the operator verifies these gates may the repository deployment layout variable be set to `split`. The application release script refuses any other value and uses only the app state key. A workflow run before that setting must not start a new app-root plan/apply.

## Recovery

On any plan error, unexpected diff, failed import, or failed post-migration verification, stop plans/releases in every root and preserve all state versions and plan artifacts. Do not apply a partially reviewed plan. Recovery is a separately reviewed declarative Terraform operation: reintroduce the original root configuration at the pre-migration commit, generate local import blocks for the exact 55 existing resource instances with `--layer legacy`, then plan/import those existing identities. Once old-root ownership is verified, use reviewed `removed { destroy = false }` blocks in the destination roots to forget their bindings. This may temporarily place an identity in two state files while recovery runs; freeze all other plans and releases until the final state has one owner per resource. Never recreate, replace, or destroy AWS resources as a recovery shortcut; never edit/push state manually. Do not set the `split` layout flag until recovery or migration completes cleanly.

## Planning and CI

`.github/workflows/terraform-ci.yml` formats, initializes without a backend, and validates the legacy migration source plus both destination roots. These checks do not prove imports match live infrastructure. Each state-backed plan requires its root's backend/configuration, the correct dependency order, a protected environment, and a complete plan review. There is no automatic apply in Terraform CI. The app deploy is blocked until the state layout variable is enabled after migration verification.
