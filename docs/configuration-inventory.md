# Configuration inventory

The active mapping is `ops/configuration/parameter-mapping.yaml`: 24 development and 30 production destinations from 18 distinct source keys per environment. All generated entries are `String`, `secret: false`, `validations: [required]`; no secret payload, unmanaged parameter or shared source is needed.

Bootstrap publishes six Standard Strings per environment; its runtime-role key waits until that role exists. Each matching application state publishes twelve keys; its two API keys wait for managed API DNS. The owned source attributes and exact-key **producer write** policies are listed below. #237 replaces public reader admission with three authorization tags; its code is distinct from an approved live policy/tag rollout (see the [rollout guide](../infra/terraform/iam-bootstrap/POLICY_DESIGN.md#ordered-rollout-and-rollback-237)). Initial publication, all 36 owned values and populated audits are [verified](https://github.com/alanlima/pawlocal/issues/206#issuecomment-6344710835).

Integrated [development](https://github.com/alanlima/pawlocal/actions/runs/39809521175) and [production](https://github.com/alanlima/pawlocal/actions/runs/39812132462) releases verified enforced reconciliation, same-run frontend publication and served OAuth host/client/callback/scopes. Legacy deletion and preservation evidence is recorded below. Cognito replacement, stale-bundle rejection and destroy/reapply recovery were tested in isolated fixtures; production was not destroyed or replaced for testing.

Post-cleanup enforce succeeded with all 24 targets unchanged in [development](https://github.com/alanlima/pawlocal/actions/runs/39840788620) and all 30 unchanged in [production](https://github.com/alanlima/pawlocal/actions/runs/39840792514).

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

During #205 setup on 2026-10-22, the orchestrator established both existing production recovery target Environments with the required owner reviewer and main-only branch policy, then verified only operator `AWS_REGION` and `PAWLOCAL_TF_STATE_BUCKET` settings/read-back. Their six generated destinations are now verified by the populated production audit linked above. No destroy was invoked and no new credential or reader-role trust was added for those targets.

## Entry settings and operator inputs (outside synchronization)

These are not automatically added as Parameter Store mappings. Their lifecycle owner is the operator unless stated otherwise.

| Setting | Location/consumer | Type and validation | Setup/status |
|---|---|---|---|
| AWS_REGION | Matching release and plan/apply Environments, plus production-destroy-prepare and production-destroy; AWS session setup | Variable; supported AWS region, must match owned resources | Required before AWS reads; retain existing operator configuration; explicitly initialize protected production recovery targets |
| PAWLOCAL_CONFIG_READER_ROLE_ARN | Matching protected apply Environment for reconciliation OIDC; matching release Environment for required initial setup/read-back | Variable; exact reviewed bootstrap output, matching account/environment | #205 setup/read-back and reader OIDC audit verified in both environments; bootstrap owns role |
| PAWLOCAL_CONFIG_GITHUB_TOKEN | Matching protected apply Environment, callable workflow secret | Secret; fine-grained PAT selected only for `alanlima/pawlocal`, Environments write and implicit Metadata read | Scoped credential/API access and populated writes verified in both apply Environments; see initial-publication evidence above; no token payload recorded |
| PAWLOCAL_TF_STATE_BUCKET | P, A, production-destroy-prepare, production-destroy; Terraform backend | Variable; approved existing state bucket | Existing entry setting, not automatically synchronized; explicitly initialize protected production recovery targets |
| PAWLOCAL_DOMAIN_NAME, PAWLOCAL_ROUTE53_ZONE_ID | P; environment root domain/DNS inputs | Variables; approved matching domain and hosted zone | Existing operator inputs; naming is not DNS authorization |
| PAWLOCAL_CLOUDFRONT_CERTIFICATE_ARN | P; Terraform certificate input | Existing secret setting; approved matching certificate ARN | Preserve current storage/configuration; no copying into Parameter Store |
| PAWLOCAL_DEPLOY_ADAPTER_PATH | R; frontend release adapter | Variable; reviewed repository adapter path | Static input; retain |
| PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS | Repository; Terraform diagnostics | Variable; exact `true` enables existing diagnostic mode | Existing operator control; do not change through reconciliation |
| PAWLOCAL_ONCALL_RECEIVER_CONFIG | Matching plan Environment; production-plan also supplies receiver configuration to production recovery plans | Public JSON operator input, default `null`; validated numeric IDs, bounded service/alert allow-lists and optional exact existing KMS ARN | #227 proposed opt-in, not live-configured; intentionally outside synchronization, no secret payloads; apply uses saved plan |
| TF_VAR_oncall_environments | iam-bootstrap-plan and iam-bootstrap-apply | Public JSON set of development/production, default `[]` | #227 bootstrap identity opt-in; effective values bound to reviewed saved plan, no live setup performed |
| TF_VAR_oncall_receiver_kms_key_arns | iam-bootstrap-plan and iam-bootstrap-apply | Public JSON map of matching environment to exact existing same-account/region KMS key ARN, default `{}` | #227 optional explicit decrypt envelope; no key created or wildcard grant when absent |


Release constants (`VITE_RELEASE_ENV`, mock-backend false, telemetry false, selected commit/image) remain workflow-owned. Generated Lightsail principal, DSQL endpoint/database role, Cognito issuer and delegated-role verification outputs have current Terraform/backend/seed consumers but no new GitHub synchronization target in this contract. Keep the separately protected `development-seed` settings untouched. The bootstrap runtime trust still consumes its exact matching Lightsail principal through the separately reviewed bootstrap input; this project does not automate that handoff or #191.

## Unmanaged parameters

**None.** All currently approved Parameter Store keys above are generated non-secret configuration assigned to one Terraform owner. The required GitHub token resides in the protected GitHub Environment, not Parameter Store. No static AWS keys, GitHub App-ID, installation-ID, private-key, application secret or other credential parameter has an actual need here. Do not pre-create Terraform-owned keys with CLI setup. Adding a real unmanaged source requires an inventory/mapping update and the applicable authorization before initialization.

## Obsolete history

The legacy release records below were retired and deleted on 2026-10-23 because they have no current release/recovery consumer. Protected cleanup succeeded in [development](https://github.com/alanlima/pawlocal/actions/runs/39840236693) and [production](https://github.com/alanlima/pawlocal/actions/runs/39840241046): exactly 13 variables and 3 secrets removed from each release Environment. A direct comparison across nine Environments verified every other variable, secret metadata record and Environment setting unchanged, including plan/apply, recovery and `development-seed`.

Each history entry applies only to R for development and production; lifecycle owner is the operator/legacy release configuration. Validation is confirmed consumer absence; `store_key: none (legacy GitHub-only)`. Each row inherits the retirement/deletion date and evidence above. Keep historical source, target, type, validation, consumer and owner details after retirement; a rename adds a new active row without removing the old record.

| GitHub name | Type / secret flag | Historical purpose | Status |
|---|---|---|---|
| PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON | Variable / false | Legacy VM SSH baseline | Deleted in R |
| PAWLOCAL_CERTIFICATE_ARN | Variable / false | Legacy certificate handoff | Deleted in R |
| PAWLOCAL_COGNITO_APP_CLIENT_ID | Variable / false | Superseded client variable | Deleted in R |
| PAWLOCAL_COGNITO_ISSUER | Variable / false | Legacy API auth handoff | Deleted in R |
| PAWLOCAL_DEPLOY_HOST | Variable / false | Legacy SSH deployment | Deleted in R |
| PAWLOCAL_DEPLOY_KNOWN_HOSTS | Variable / false | Legacy SSH host verification | Deleted in R |
| PAWLOCAL_DEPLOY_MODE | Variable / false | Legacy adapter selection | Deleted in R |
| PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON | Variable / false | Legacy VM authorized keys | Deleted in R |
| PAWLOCAL_DOMAIN_NAME | Variable / false | Legacy release domain input | Deleted in R; P remains required |
| PAWLOCAL_DSQL_DATABASE_ROLE | Variable / false | Legacy database handoff | Deleted in R; runtime/seed unchanged |
| PAWLOCAL_DSQL_ENDPOINT | Variable / false | Legacy database handoff | Deleted in R; runtime/seed unchanged |
| PAWLOCAL_TERRAFORM_ROLE_ARN | Variable / false | Legacy combined-state identity | Deleted in R |
| PAWLOCAL_TF_STATE_BUCKET | Variable / false | Legacy release backend setting | Deleted in R; P/A remain required |
| PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY | Secret / true | Legacy SSH deployment credential | Deleted in R |
| PAWLOCAL_DSQL_ACCESS_KEY_ID | Secret / true | Legacy static database identity | Deleted in R |
| PAWLOCAL_DSQL_SECRET_ACCESS_KEY | Secret / true | Legacy static database credential | Deleted in R |

Do not copy these credentials into Parameter Store. Keep these dated records after deletion and record actual deletion evidence separately; obsolete synchronization entries never remain executable. The cleanup code contains only the approved exact deletion allowlist, not active mappings.

## Staged monitoring sources (#223; not live accepted)

The single `parameter-mapping.yaml` contains ordinary and reviewed public monitoring rows. #228 adds two real recovery consumers in each matching on-call Environment: existing `config/frontend/base-url` → `PAWLOCAL_PUBLIC_BASE_URL` and `config/api/base-url` → `VITE_API_BASE_URL`. This adds no source parameter or IAM grant. Including staged monitoring, the manifest now has 33 development and 39 production destinations from 24 distinct sources per environment; the opening baseline counts remain historical live evidence. The copy operation warns/skips missing sources or destination Environments; genuine permission errors fail. Runtime secrets are not copied. Query-token synchronization remains a proposed later secret-reader scope and is not in the active manifest. Source production and consumer integration remain #224–#228; live tag-policy rollout is a separate predecessor.

Paths below are prefixed `/pawlocal/{environment}/` for development/production. The table records planned destinations; presence does not activate telemetry. R = matching release, P = matching plan, O = `oncall-{environment}`.

| Source suffix | Type / secret | GitHub name / target | Consumer / owner |
|---|---|---|---|
| config/observability/enabled | String / false | PAWLOCAL_TELEMETRY_ENABLED / P | backend runtime mode; matching application state |
| config/frontend/telemetry-enabled | String / false | VITE_TELEMETRY_ENABLED / R | independent frontend build mode; matching application state |
| config/grafana/otlp-endpoint | String / false | OTEL_EXPORTER_OTLP_ENDPOINT / P | direct backend exporter; application state discovered via grafana_cloud_stack |
| config/grafana/otlp-instance-id | String / false | PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID / P | backend auth identity; application state discovered via grafana_cloud_stack |
| config/grafana/faro-collector-url | String / false | VITE_FARO_COLLECTOR_URL / R | public Faro key path; application state discovered via grafana_frontend_o11y_app |
| config/grafana/stack-url | String / false | PAWLOCAL_GRAFANA_URL / O | trusted preflight; application state using discovered or actual Grafana input |
| config/oncall/webhook-url | String / false | PAWLOCAL_GRAFANA_WEBHOOK_URL / O | contact-point verification; application state derives Function URL |
| secrets/grafana/query-token | SecureString / true | Proposed PAWLOCAL_GRAFANA_QUERY_TOKEN / O secret | Future separate reader/secret lifecycle approval; no active copy row |

Runtime-only `secrets/grafana/otlp-token`, `secrets/grafana/webhook-hmac`, and `secrets/oncall/dispatch-app-private-key` never synchronize to GitHub. OpenAI/publisher App credentials remain separately scoped GitHub secrets. No secret payload is managed by this PR. Future source creation/rotation requires an explicit reviewed lifecycle satisfying Terraform ownership and no-secret-in-state requirements; no blanket CLI exception is granted.

## Planned incident-receiver runtime sources (Issue #227)

The earlier unmanaged-parameter inventory above describes the pre-monitoring baseline. #227 introduces actual dormant runtime consumers below, rather than pre-creating unused configuration. Status: **planned, not populated or live-verified**. SecureString values remain operator-managed under a separately approved lifecycle; Terraform reads no values, creates no secret payload and adds no duplicate Secrets Manager copy.

| Source | Consumer / destination | Ownership and validation |
|---|---|---|
| /pawlocal/<environment>/secrets/grafana/webhook-hmac | Matching receiver only; no GitHub synchronization | Approved secret owner lifecycle; SecureString, minimum 32 UTF-8 bytes; exact SSM read and optional existing-key encryption context |
| /pawlocal/<environment>/secrets/oncall/dispatch-app-private-key | Matching receiver only; no GitHub synchronization | Separate dispatch-only GitHub App identity; RSA PEM at least 2048 bits; exact SSM read and optional existing-key encryption context |

Actual creation/population/rotation needs a reviewed owner procedure before live mutation. Default `aws/ssm` decryption under the final execution-role boundary is an activation proof gap; optional exact existing KMS grants do not imply a new customer-managed key. Follow the [receiver runbook](../ops/incident-response/README.md). Public App IDs remain in the explicit operator JSON input, not extra unused SSM parameters.

## Hosted telemetry operator input (#225)

`PAWLOCAL_HOSTED_OBSERVABILITY_CONFIG` is an optional public plan-Environment variable, not an SSM-derived credential: it supplies the reviewed Grafana object to Terraform so the matching application state can publish its owned Strings. Null keeps export disabled. See the [operations contract](hosted-telemetry-operations.md) for exact fields, runtime-only OTLP source, validation, release evidence and live limitations. It must not contain private token payloads.

## Proposed runtime secret lifecycle (#241)

The [unaccepted DEC-013 proposal](specs/monitoring-secret-lifecycle.md) lists four exact source suffixes, application-state ownership and distinct runtime/query consumers. It evaluates state-free write-only creation/rotation and exact ephemeral maintenance reads; no resource or read/write grant is added here. Runtime-only OTLP/HMAC/dispatch values stay outside GitHub synchronization; query-token copying remains a separately reviewed inactive proposal. Public tag-reader/YAML semantics are unchanged.

Frontend-first #225 amendment: public application-owned `/pawlocal/{environment}/config/frontend/telemetry-enabled` maps to `VITE_TELEMETRY_ENABLED` in R, independent of the backend observability flag. See the frontend-first rollout in `docs/hosted-telemetry-operations.md` for the operator JSON, migration order and versioned release contract.
