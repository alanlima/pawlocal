# Configuration inventory

The active mapping is `ops/configuration/parameter-mapping.yaml`: 24 development and 30 production destinations from 18 distinct source keys per environment. All generated entries are `String`, `secret: false`, `validations: [required]`; no secret payload, unmanaged parameter or shared source is needed.

Bootstrap publishes six Standard Strings per environment; its runtime-role key waits until that role exists. Each matching application state publishes twelve keys; its two API keys wait for managed API DNS. The owned source attributes and exact-key policy are listed below. Runtime evidence and current rollout status belong in #206 and its PRs.


## Generated parameter entries

Prefix every key suffix with `/pawlocal/{environment}/config/`. R = `{environment}` (release), P = `{environment}-plan`, A = `{environment}-apply`; each listed target expands to its own YAML entry. B = `iam-bootstrap` lifecycle owner; E = matching application state lifecycle owner. These aliases are documentation only, never extra YAML fields. Each row inherits the type, secret flag, validations and supported environments above.

| Key suffix | GitHub `env_name` | `github_environment` | Owner | Actual source and consumer/purpose |
|---|---|---|---|---|
| iam/terraform-plan-role-arn | PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN | P, A | B | `aws_iam_role.github_terraform["<environment>-plan"].arn`; Terraform plan OIDC, retained in A by agreed mapping contract |
| iam/terraform-apply-role-arn | PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN | A | B | `aws_iam_role.github_terraform["<environment>-apply"].arn`; protected saved-plan apply OIDC |
| aws/account-id | PAWLOCAL_AWS_ACCOUNT_ID | P, A | B | `data.aws_caller_identity.current.account_id`; account and delegated-role validation |
| terraform/plan-bucket | PAWLOCAL_TERRAFORM_PLAN_BUCKET | P, A | B | `local.plan_transfer_bucket_name`, backed by bootstrap plan-transfer resource; private saved-plan upload/download |
| iam/frontend-publish-role-arn | PAWLOCAL_DEPLOY_ROLE_ARN | R | B | `aws_iam_role.identity_app["<environment>_frontend"].arn`; frontend publisher OIDC |
| iam/runtime-role-arn | PAWLOCAL_RUNTIME_ROLE_ARN | P, A | B | Matching `aws_iam_role.development_runtime[0].arn` / `production_runtime[0].arn`, only when created; environment plan's runtime trust/DSQL/deployment input |
| frontend/base-url | PAWLOCAL_PUBLIC_BASE_URL | R | E | HTTPS origin from managed `aws_route53_record.frontend_a.fqdn`; publish/verify adapter and deployment URL |
| api/health-url | PAWLOCAL_API_HEALTH_URL | R | E | HTTPS managed `aws_route53_record.api[0].fqdn` plus `/health`, only when deployed; public health/database smoke verification |
| frontend/bucket | PAWLOCAL_FRONTEND_BUCKET | R | E | `aws_s3_bucket.frontend.bucket`; frontend artifact publication |
| frontend/cloudfront-distribution-id | PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID | R | E | `aws_cloudfront_distribution.frontend.id`; CDN publication/invalidation |
| frontend/cloudfront-distribution-arn | PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN | P, A | E | `aws_cloudfront_distribution.frontend.arn`; exact generated-resource environment policy input |
| frontend/cloudfront-oac-arn | PAWLOCAL_CLOUDFRONT_OAC_ARN | P, A | E | `aws_cloudfront_origin_access_control.frontend.arn`; exact generated-resource environment policy input |
| auth/client-id | VITE_COGNITO_CLIENT_ID | R | E | `aws_cognito_user_pool_client.browser.id`; frontend public OAuth browser client |
| api/base-url | VITE_API_BASE_URL | R | E | HTTPS managed `aws_route53_record.api[0].fqdn` plus `/api/v1`, only when deployed; HTTP service adapter |
| auth/domain | VITE_COGNITO_DOMAIN | R | E | `aws_cognito_user_pool_domain.application.domain` and owning region, full HTTPS Cognito origin; hosted sign-in/token/logout endpoints |
| auth/redirect-uri | VITE_COGNITO_REDIRECT_URI | R | E | Managed browser client `callback_urls` matching frontend `/auth/callback`; OAuth callback |
| auth/logout-uri | VITE_COGNITO_LOGOUT_URI | R | E | Managed browser client `logout_urls` matching frontend `/`; OAuth logout return |
| auth/scopes | VITE_COGNITO_SCOPES | R | E | Managed browser client `allowed_oauth_scopes`, space joined; OAuth authorization scopes |

Sources refer to `infra/terraform/iam-bootstrap/{main,identity_roles,configuration_parameters,outputs}.tf` and `infra/terraform/modules/pawlocal-environment/{main,configuration,outputs}.tf`. The application output includes canonical API base, Cognito domain, callback, logout and space-separated scopes from those managed attributes. Consumers are `.github/workflows/terraform-environment.yml`, `fullstack-release.yml`, `deploy-production.yml`, the frontend auth/service configuration and `ops/deployment-adapters/lightsail-dsql.sh`. P consumes the generated handoff values when planning; A applies the exact saved plan and consumes its AWS/account/plan-transfer settings. The agreed P/A destinations are retained even where A does not independently evaluate a value. Keep destroy/recovery consumption in the review before retiring any target.

### Additional existing production recovery destinations

These six destinations use three existing source keys above, with the same String type, false secret flag, required validation, bootstrap lifecycle owner and purpose. Their `environment` is `[production]` only. Each row expands into two mapping entries, one for each exact target; no new source parameter is added.

| `store_key` | GitHub `env_name` | Exact `github_environment` targets | Consumer |
|---|---|---|---|
| /pawlocal/production/config/iam/terraform-apply-role-arn | PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN | production-destroy-prepare, production-destroy | Existing protected production teardown-preparation/final-destroy apply OIDC |
| /pawlocal/production/config/aws/account-id | PAWLOCAL_AWS_ACCOUNT_ID | production-destroy-prepare, production-destroy | Existing production recovery account and delegated-role validation |
| /pawlocal/production/config/terraform/plan-bucket | PAWLOCAL_TERRAFORM_PLAN_BUCKET | production-destroy-prepare, production-destroy | Existing production recovery private saved-plan download |

`terraform-environment-destroy.yml` is the actual consumer. Both target Environments were absent in the 2026-10-22 read-only GitHub inventory; create/review their required reviewer and main-only branch policies explicitly before reconciliation. Never let synchronization create an unprotected Environment. No plan-role ARN is consumed by these apply jobs, so do not map one there. No development destroy target or reader-role OIDC trust is added.

During #205 setup on 2026-10-22, the orchestrator established both existing production recovery target Environments with the required owner reviewer and main-only branch policy, then verified only operator `AWS_REGION` and `PAWLOCAL_TF_STATE_BUCKET` settings/read-back. Their generated variables remain pending actual #206 sources and reconciliation. No destroy was invoked and no new credential or reader-role trust was added for those targets.

## Entry settings and operator inputs (outside synchronization)

These are not automatically added as Parameter Store mappings. Their lifecycle owner is the operator unless stated otherwise.

| Setting | Location/consumer | Type and validation | Setup/status |
|---|---|---|---|
| AWS_REGION | Matching release and plan/apply Environments, plus production-destroy-prepare and production-destroy; AWS session setup | Variable; supported AWS region, must match owned resources | Required before AWS reads; retain existing operator configuration; explicitly initialize protected production recovery targets |
| PAWLOCAL_CONFIG_READER_ROLE_ARN | Matching protected apply Environment for reconciliation OIDC; matching release Environment for required initial setup/read-back | Variable; exact reviewed bootstrap output, matching account/environment | #205 setup/read-back and reader OIDC audit verified in both environments; bootstrap owns role |
| PAWLOCAL_CONFIG_GITHUB_TOKEN | Matching protected apply Environment, callable workflow secret | Secret; fine-grained PAT selected only for `alanlima/pawlocal`, Environments write and implicit Metadata read | #205 scoped credential/API access verified in both apply Environments; populated-source writes remain #206 acceptance; no token payload recorded |
| PAWLOCAL_TF_STATE_BUCKET | P, A, production-destroy-prepare, production-destroy; Terraform backend | Variable; approved existing state bucket | Existing entry setting, not automatically synchronized; explicitly initialize protected production recovery targets |
| PAWLOCAL_DOMAIN_NAME, PAWLOCAL_ROUTE53_ZONE_ID | P; environment root domain/DNS inputs | Variables; approved matching domain and hosted zone | Existing operator inputs; naming is not DNS authorization |
| PAWLOCAL_CLOUDFRONT_CERTIFICATE_ARN | P; Terraform certificate input | Existing secret setting; approved matching certificate ARN | Preserve current storage/configuration; no copying into Parameter Store |
| PAWLOCAL_DEPLOY_ADAPTER_PATH | R; frontend release adapter | Variable; reviewed repository adapter path | Static input; retain |
| PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS | Repository; Terraform diagnostics | Variable; exact `true` enables existing diagnostic mode | Existing operator control; do not change through reconciliation |

Release constants (`VITE_RELEASE_ENV`, mock-backend false, telemetry false, selected commit/image) remain workflow-owned. Generated Lightsail principal, DSQL endpoint/database role, Cognito issuer and delegated-role verification outputs have current Terraform/backend/seed consumers but no new GitHub synchronization target in this contract. Keep the separately protected `development-seed` settings untouched. The bootstrap runtime trust still consumes its exact matching Lightsail principal through the separately reviewed bootstrap input; this project does not automate that handoff or #191.

## Unmanaged parameters

**None.** All currently approved Parameter Store keys above are generated non-secret configuration assigned to one Terraform owner. The required GitHub token resides in the protected GitHub Environment, not Parameter Store. No static AWS keys, GitHub App-ID, installation-ID, private-key, application secret or other credential parameter has an actual need here. Do not pre-create Terraform-owned keys with CLI setup. Adding a real unmanaged source requires an inventory/mapping update and the applicable authorization before initialization.

## Obsolete history

The legacy release records below have no active synchronization mapping. Their retirement date is 2026-10-23; reason: no current release/recovery consumer after the reviewed configuration integration. Actual GitHub deletion remains pending the protected exact-name cleanup run; retirement does not claim deletion. Historical entries must retain full `store_key`, environment, GitHub target/name, type, secret flag, validations, purpose/consumer and lifecycle owner plus obsolete date (`YYYY-MM-DD`), reason and separate confirmed-deletion status. A rename preserves the original row here and creates the new active row. Legacy settings that never had a Parameter Store source use `store_key: none (legacy GitHub-only)` rather than inventing a historical AWS key.

The following is #206's exact legacy cleanup history/allowlist. Every entry applies only to R for development and production; lifecycle owner is the operator/legacy release configuration. Validation is current-consumer absence before retirement; source is none (legacy GitHub-only). Each row inherits obsolete date 2026-10-23, the reason above, and pending protected-deletion status. Runtime cleanup repeats the consumer check before deletion.

| GitHub name | Type / secret flag | Historical purpose | Status |
|---|---|---|---|
| PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON | Variable / false | Legacy VM SSH baseline | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_CERTIFICATE_ARN | Variable / false | Legacy certificate handoff | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_COGNITO_APP_CLIENT_ID | Variable / false | Superseded client variable | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_COGNITO_ISSUER | Variable / false | Legacy API auth handoff | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_DEPLOY_HOST | Variable / false | Legacy SSH deployment | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_DEPLOY_KNOWN_HOSTS | Variable / false | Legacy SSH host verification | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_DEPLOY_MODE | Variable / false | Legacy adapter selection | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON | Variable / false | Legacy VM authorized keys | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_DOMAIN_NAME | Variable / false | Legacy release domain input | Pending cleanup in R only; P remains required |
| PAWLOCAL_DSQL_DATABASE_ROLE | Variable / false | Legacy database handoff | Pending cleanup in R only; runtime/seed unaffected |
| PAWLOCAL_DSQL_ENDPOINT | Variable / false | Legacy database handoff | Pending cleanup in R only; runtime/seed unaffected |
| PAWLOCAL_TERRAFORM_ROLE_ARN | Variable / false | Legacy combined-state identity | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_TF_STATE_BUCKET | Variable / false | Legacy release backend setting | Pending cleanup in R only; P/A remain required |
| PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY | Secret / true | Legacy SSH deployment credential | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_DSQL_ACCESS_KEY_ID | Secret / true | Legacy static database identity | Pending protected deletion; runtime consumer check required |
| PAWLOCAL_DSQL_SECRET_ACCESS_KEY | Secret / true | Legacy static database credential | Pending protected deletion; runtime consumer check required |

Do not copy these credentials into Parameter Store. Keep these dated records after deletion and record actual deletion evidence separately; obsolete synchronization entries never remain executable. The cleanup code contains only the approved exact deletion allowlist, not active mappings.
