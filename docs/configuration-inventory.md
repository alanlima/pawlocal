# Configuration inventory

Specification baseline for #204 under #203. Entries below are approved sources/destinations for implementation in #205/#206, not a claim that parameters or mappings are deployed. Read-only AWS inventory during this task found no existing `/pawlocal/` parameters. All generated entries are `String`, `secret: false`, `validations: [required]`, apply to both `development` and `production`, and have no secret payload. No genuinely shared parameter is currently needed.

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
| frontend/base-url | PAWLOCAL_PUBLIC_BASE_URL | R | E | Module `targets.frontend_url` from managed frontend configuration; publish/verify adapter and deployment URL |
| api/health-url | PAWLOCAL_API_HEALTH_URL | R | E | Module `targets.api_health_url`; public health/database smoke verification |
| frontend/bucket | PAWLOCAL_FRONTEND_BUCKET | R | E | `aws_s3_bucket.frontend.bucket`; frontend artifact publication |
| frontend/cloudfront-distribution-id | PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID | R | E | `aws_cloudfront_distribution.frontend.id`; CDN publication/invalidation |
| frontend/cloudfront-distribution-arn | PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN | P, A | E | `aws_cloudfront_distribution.frontend.arn`; exact generated-resource environment policy input |
| frontend/cloudfront-oac-arn | PAWLOCAL_CLOUDFRONT_OAC_ARN | P, A | E | `aws_cloudfront_origin_access_control.frontend.arn`; exact generated-resource environment policy input |
| auth/client-id | VITE_COGNITO_CLIENT_ID | R | E | `aws_cognito_user_pool_client.browser.id`; frontend public OAuth browser client |
| api/base-url | VITE_API_BASE_URL | R | E | Matching managed API hostname, HTTPS origin plus `/api/v1`; HTTP service adapter |
| auth/domain | VITE_COGNITO_DOMAIN | R | E | `aws_cognito_user_pool_domain.application.domain` and owning region, full HTTPS Cognito origin; hosted sign-in/token/logout endpoints |
| auth/redirect-uri | VITE_COGNITO_REDIRECT_URI | R | E | Managed browser client `callback_urls` matching frontend `/auth/callback`; OAuth callback |
| auth/logout-uri | VITE_COGNITO_LOGOUT_URI | R | E | Managed browser client `logout_urls` matching frontend `/`; OAuth logout return |
| auth/scopes | VITE_COGNITO_SCOPES | R | E | Managed browser client `allowed_oauth_scopes`, space joined; OAuth authorization scopes |

Sources refer to `infra/terraform/iam-bootstrap/{main,identity_roles,outputs}.tf` and `infra/terraform/modules/pawlocal-environment/{main,outputs}.tf`. Missing canonical public outputs are added in #206 directly from the attributes above. Consumers are `.github/workflows/terraform-environment.yml`, `fullstack-release.yml`, `deploy-production.yml`, the frontend auth/service configuration and `ops/deployment-adapters/lightsail-dsql.sh`. P consumes the generated handoff values when planning; A applies the exact saved plan and consumes its AWS/account/plan-transfer settings. The agreed P/A destinations are retained even where A does not independently evaluate a value. Keep destroy/recovery consumption in the review before retiring any target.

## Entry settings and operator inputs (outside synchronization)

These are not automatically added as Parameter Store mappings. Their lifecycle owner is the operator unless stated otherwise.

| Setting | Location/consumer | Type and validation | Setup/status |
|---|---|---|---|
| AWS_REGION | Matching release and plan/apply Environments; AWS session setup | Variable; supported AWS region, must match owned resources | Required before AWS reads; retain existing operator configuration |
| PAWLOCAL_CONFIG_READER_ROLE_ARN | Matching protected apply Environment for reconciliation OIDC; matching release Environment for required initial setup/read-back | Variable; exact reviewed bootstrap output, matching account/environment | #205 initial setup/read-back in both locations; bootstrap owns role; no current live reader-role claim |
| PAWLOCAL_CONFIG_GITHUB_TOKEN | Matching protected apply Environment, callable workflow secret | Secret; fine-grained PAT selected only for `alanlima/pawlocal`, Environments write and implicit Metadata read | Scoped credential configured in both apply Environments 2026-10-22; read-only API access checked; runtime writes remain #205 verification; no token payload in this inventory |
| PAWLOCAL_TF_STATE_BUCKET | P, A; Terraform backend | Variable; approved existing state bucket | Existing entry setting, not automatically synchronized |
| PAWLOCAL_DOMAIN_NAME, PAWLOCAL_ROUTE53_ZONE_ID | P; environment root domain/DNS inputs | Variables; approved matching domain and hosted zone | Existing operator inputs; naming is not DNS authorization |
| PAWLOCAL_CLOUDFRONT_CERTIFICATE_ARN | P; Terraform certificate input | Existing secret setting; approved matching certificate ARN | Preserve current storage/configuration; no copying into Parameter Store |
| PAWLOCAL_DEPLOY_ADAPTER_PATH | R; frontend release adapter | Variable; reviewed repository adapter path | Static input; retain |
| PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS | Repository; Terraform diagnostics | Variable; exact `true` enables existing diagnostic mode | Existing operator control; do not change through reconciliation |

Release constants (`VITE_RELEASE_ENV`, mock-backend false, telemetry false, selected commit/image) remain workflow-owned. Generated Lightsail principal, DSQL endpoint/database role, Cognito issuer and delegated-role verification outputs have current Terraform/backend/seed consumers but no new GitHub synchronization target in this contract. Keep the separately protected `development-seed` settings untouched. The bootstrap runtime trust still consumes its exact matching Lightsail principal through the separately reviewed bootstrap input; this project does not automate that handoff or #191.

## Unmanaged parameters

**None.** All currently approved Parameter Store keys above are generated non-secret configuration assigned to one Terraform owner. The required GitHub token resides in the protected GitHub Environment, not Parameter Store. No static AWS keys, GitHub App-ID, installation-ID, private-key, application secret or other credential parameter has an actual need here. Do not pre-create Terraform-owned keys with CLI setup. Adding a real unmanaged source requires an inventory/mapping update and the applicable authorization before initialization.

## Obsolete history and pending cleanup

No active mapping has yet been retired, and this specification does not claim any AWS or GitHub deletion. Historical entries must retain full `store_key`, environment, GitHub target/name, type, secret flag, validations, purpose/consumer and lifecycle owner plus obsolete date (`YYYY-MM-DD`), reason and separate confirmed-deletion status. A rename preserves the original row here and creates the new active row. Legacy settings that never had a Parameter Store source use `store_key: none (legacy GitHub-only)` rather than inventing a historical AWS key.

The following is #206's exact pending cleanup inventory, not an instruction to delete during #204. Every entry applies only to R for development and production; lifecycle owner is the operator/legacy release configuration. Validation is current-consumer absence before retirement; source is none (legacy GitHub-only). No obsolete date is assigned until retirement is verified.

| GitHub name | Type / secret flag | Historical purpose | Status |
|---|---|---|---|
| PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON | Variable / false | Legacy VM SSH baseline | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_CERTIFICATE_ARN | Variable / false | Legacy certificate handoff | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_COGNITO_APP_CLIENT_ID | Variable / false | Superseded client variable | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_COGNITO_ISSUER | Variable / false | Legacy API auth handoff | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_DEPLOY_HOST | Variable / false | Legacy SSH deployment | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_DEPLOY_KNOWN_HOSTS | Variable / false | Legacy SSH host verification | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_DEPLOY_MODE | Variable / false | Legacy adapter selection | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON | Variable / false | Legacy VM authorized keys | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_DOMAIN_NAME | Variable / false | Legacy release domain input | Pending cleanup in R only; P remains required |
| PAWLOCAL_DSQL_DATABASE_ROLE | Variable / false | Legacy database handoff | Pending cleanup in R only; runtime/seed unaffected |
| PAWLOCAL_DSQL_ENDPOINT | Variable / false | Legacy database handoff | Pending cleanup in R only; runtime/seed unaffected |
| PAWLOCAL_TERRAFORM_ROLE_ARN | Variable / false | Legacy combined-state identity | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_TF_STATE_BUCKET | Variable / false | Legacy release backend setting | Pending cleanup in R only; P/A remain required |
| PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY | Secret / true | Legacy SSH deployment credential | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_DSQL_ACCESS_KEY_ID | Secret / true | Legacy static database identity | Pending consumer proof and exact-target cleanup |
| PAWLOCAL_DSQL_SECRET_ACCESS_KEY | Secret / true | Legacy static database credential | Pending consumer proof and exact-target cleanup |

Do not copy these obsolete credentials into Parameter Store. After verified retirement move records into dated history with original fields and evidence of actual deletion or explicit remaining-resource status; obsolete mappings never remain executable.
