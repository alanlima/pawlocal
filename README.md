# PawLocal

PawLocal is a community-maintained directory of dog-friendly places across South East Queensland, from the Gold Coast to the Sunshine Coast.

## Project status

**Stages 2, 3, and 3.1 are complete and reviewed. Stage 4 is in progress.** Issue #135 approves a greenfield Terraform design with a standalone IAM bootstrap state and clean development and production application states while preserving the Issue #75 Lightsail Container Services and Aurora DSQL architecture. The legacy destroy run was partial, so current AWS resources and state ownership must be verified through read-only inspection before implementation. No Issue #135 bootstrap import, application plan/apply, or deployment is complete. Telemetry is disabled for the initial release; enablement is deferred to [Issue #59](https://github.com/alanlima/pawlocal/issues/59). Backup, HA, RPO/RTO, restore, recovery, and rollback are out of MVP scope and deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44). CI validates frontend and backend changes, the combined local Compose stack, and Terraform configuration. Mock data is selected only when `VITE_USE_MOCK_BACKEND=true`; the combined Compose stack selects the HTTP adapter. Place access and facility details are not represented as verified facts. See [local development setup](frontend/README.md).

Issue #43 records the full-stack release policy: PR CI, automatic deployment of successful main releases to development, and a separate manually dispatched production promotion of a release already verified in development. Issue #135 now owns the Terraform structure and deployment-path implementation. Existing combined-root Terraform and deployment workflows are historical reference only and must not be run as the new path. Before any Issue #135 Terraform, workflow, or deployment-helper implementation merges, the legacy automatic development-deploy path must be disabled or made fail-closed and verified unable to run from that merge. Keep it disabled until the new roots, targets, credentials, and release path are configured and independently reviewed. See the historical [AWS deployment record](docs/deployment-aws-frontend.md), [hosting proposal](docs/stage4-hosting-options.md), and [decision log](docs/decisions.md).

## Project documentation

- [Product specification](product-spec.md)
- [OpenAPI contract](openapi.yaml)
- [Architecture](docs/architecture.md)
- [Implementation plan and issue proposals](docs/implementation-plan.md)
- [Agent workflow](docs/agent-workflow.md)
- [Model policy](docs/model-policy.md)
- [Decisions](docs/decisions.md)
- [Testing approach](docs/testing.md)
- [Historical AWS deployment record](docs/deployment-aws-frontend.md)
- [AI usage report](docs/ai-usage-report.md)

## Planned stack

React, TypeScript, Vite and Tailwind CSS; Python, FastAPI and Pydantic; PostgreSQL with SQLAlchemy 2 and Alembic; Docker Compose; and OpenTelemetry with Grafana, Prometheus, Loki and Tempo. Local Compose uses PostgreSQL. The owner selected Lightsail Container Services + Aurora DSQL with short-lived GitHub OIDC deployment identities; DSQL still requires live compatibility validation and deployment setup. Hosted telemetry is disabled for the initial release; backup, HA and recovery are deferred. Current cloud resource and state inventory is unverified after the partial legacy teardown.

## Backend development

Stage 3 backend setup, migration, API, and test instructions are in [backend/README.md](backend/README.md). Protected API operations validate Cognito access tokens; no Cognito or other AWS resources are provisioned in this stage.

## Frontend service mode

The frontend uses `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`. When the toggle is false or unset, it selects the typed `HttpPlaceService` and uses `VITE_API_BASE_URL` (default `/api/v1`). Vite's development server proxies that path to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`); set the target to `http://backend:8000` in Compose. Cloud releases use separate HTTPS API hosts (`api-dev.<domain>` and `api.<domain>`), while CloudFront serves frontend assets only. A failed or unavailable API remains an HTTP error and never silently switches to mock data. The checked-in `.env.example` opts into mock mode for the local demo.

HTTP-mode authentication is a host integration seam, not a PawLocal sign-in flow. The host can inject `window.pawLocalAuth` before the app loads with `getAccessToken()` returning the current Cognito access token (sync or async), and optional `signIn()`/`signOut()` callbacks. The frontend requests a fresh token for each API call, sends it only as a Bearer header, and does not persist it. Hosts own authentication UX and token refresh. Without the host provider, protected actions report that authentication is unavailable; mock demo-member mode never authenticates HTTP requests. See [frontend/README.md](frontend/README.md#host-authentication-integration) for the interface contract.

## Development

For the combined local frontend, API, PostgreSQL and observability stack, first copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). The example contains a clearly local-only PostgreSQL password placeholder; keep `.env` out of version control and replace the placeholder for your local environment. Compose requires `PAWLOCAL_POSTGRES_PASSWORD` and has no built-in credential fallback. Then run `docker compose up --build -d` from the repository root. Open PawLocal at <http://localhost:5173>, Grafana at <http://localhost:3000>, and the API health endpoint at <http://localhost:8000/health>. See [frontend README](frontend/README.md) and [backend README](backend/README.md) for ports, health checks, privacy, synthetic failures, shutdown, migrations and tests. All local Compose services bind to localhost; running the local stack requires no cloud resources.

## Issue #135 Terraform baseline

Issue #135 defines three new ownership boundaries: an IAM bootstrap state and separate development and production application states. Bootstrap owns shared OIDC trust, deployment-role identity, baseline permissions, and permissions boundaries. Each application state owns only its own resources, environment-specific managed policy, and matching attachment. The former cross-environment CloudFront retag/update exception is superseded; one environment must not alter the other.

Before implementation, use read-only AWS and Terraform inspection to determine what remains after the partial legacy teardown and to verify the exact existing deployment identity eligible for bootstrap adoption. Import no application resources into the new states. If application resources or bindings survived, stop the affected environment and escalate an exact inventory for an owner-approved, independently reviewed, Terraform-only cleanup change; amend Issue #135 and DEC-008 first if orphan adoption is required solely for cleanup. Any eligible identity import must be declared in reviewed Terraform configuration and visible in a saved plan with no duplicate ownership or unintended replacement/deletion. The owner's local higher-permission exception applies only to an independently reviewed bootstrap saved plan. All development and production application plans/applies run through their matching protected GitHub Environments and apply the exact reviewed plan.

The implementation will define the root paths, backend keys, workflow names, outputs, GitHub Environment configuration, and operator commands. They are intentionally not guessed in this documentation baseline. PRs [#113](https://github.com/alanlima/pawlocal/pull/113), [#88](https://github.com/alanlima/pawlocal/pull/88), and [#74](https://github.com/alanlima/pawlocal/pull/74) describe earlier ownership or ingress approaches and are reference-only pending explicit disposition. Open [PR #134](https://github.com/alanlima/pawlocal/pull/134) documents the partial teardown's retained-role proposal; it is not verified Issue #135 inventory or implementation evidence.

### Historical Issue #112 and combined-state record (non-actionable)

> The remainder of this section records the superseded bootstrap/combined-state process for audit context. Do not run its commands, configure its variables, or use it as Issue #135 implementation guidance.

The standalone `infra/terraform/iam-bootstrap` root uses the separate state key `pawlocal/iam-bootstrap/terraform.tfstate`. Its first reviewed Terraform apply created environment Terraform roles, dedicated legacy combined-state plan/apply roles, and a private bucket for short-lived saved plans, and imported the existing DSQL service-linked role. Their non-secret outputs are configured in the GitHub Environments. The frontend publisher-role ownership transfer is deferred until recreation; the existing app-root `destroy = false` protection remains in place. The shared GitHub OIDC provider transfer is a later separate stage. The bootstrap state does not create application resources.

The legacy operations workflow assumes `pawlocal-legacy-terraform-plan` from GitHub Environment `infrastructure-plan` and `pawlocal-legacy-terraform-apply` from `infrastructure-apply`. Configure these non-secret Environment variables only after the approved local bootstrap apply: `PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN` in `infrastructure-plan`, `PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN` in `infrastructure-apply`, and `PAWLOCAL_TERRAFORM_PLAN_BUCKET` in both Environments. Also configure `AWS_REGION`, `PAWLOCAL_AWS_ACCOUNT_ID`, `PAWLOCAL_TF_STATE_BUCKET`, `PAWLOCAL_DOMAIN_NAME`, and `PAWLOCAL_CERTIFICATE_ARN` as Environment variables in both Environments. Restrict both Environments to the protected `main` branch; require reviewers on `infrastructure-apply`. The workflow uses GitHub OIDC, checks the assumed account before Terraform, and configures the action's supported allowed-account guard. No static AWS access-key secrets are used.

The plan and apply roles transfer the exact saved plan and metadata through the bootstrap-owned S3 bucket under `plans/legacy/<run-id>/<attempt>/<stage>/`. The bucket blocks public access, enforces bucket-owner object ownership, encrypts with AES-256, versions objects, and expires current and noncurrent objects after one day. Only the plan role can upload under this prefix; only the apply role can read it. The saved plan digest and metadata remain bound to the repository, Environment, run and attempt, commit, state key, and AWS account. Never log plan contents or upload Terraform state snapshots or credentials.

The legacy combined-stack apply role can mutate application resources in the current combined root and destroy them through the explicitly approved teardown workflow. Most permissions target PawLocal bucket, Lightsail, IAM role, DSQL cluster, Cognito pool, and Route 53 scopes. **CloudFront remains a documented MVP exception:** its distribution IDs are generated, current distributions lack ownership tags, and CreateDistribution requires `Resource: "*"`; consequently the role can create distributions and update/delete any CloudFront distribution in this AWS account. OAC identifiers are generated and cannot be name-scoped, so OAC management is account-wide. Lightsail create APIs also require `Resource: "*"` and the current service resource does not pass tags. These permissions are limited to the named actions needed by the current Terraform root, but they carry account-level impact and must be reviewed before bootstrap apply. This policy does not grant AdministratorAccess or add backup, recovery, or incident-response permissions. The split development/production roles retain their separate-state permissions and do not inherit this legacy role's delete scope.

CloudFront OAC permissions use a staged handoff because OAC IDs are generated dynamically and AWS provides no tag conditions for them. Set local bootstrap input `oac_create_environment=development` for the first OAC creation. Only that environment's apply role temporarily receives `CreateOriginAccessControl` on `Resource: "*"` and wildcard OAC Get/GetConfig read access for Terraform's create/read cycle. No plan role gets temporary wildcard OAC access; `ListOriginAccessControls` is not granted. After development succeeds through GitHub Actions, retrieve its `oac_arn` output. Before starting the production plan, use the approved local Terraform bootstrap procedure to set `TF_VAR_development_oac_arn` to that ARN and `TF_VAR_oac_create_environment=production`, then review and apply the bootstrap update. Development OAC reads/updates/deletes then use only the dev ARN; only production apply temporarily gets create and wildcard read access. Set repository variable `PAWLOCAL_DEVELOPMENT_OAC_ARN` to the dev ARN for the workflow state guard. After production succeeds through GitHub Actions, set `TF_VAR_production_oac_arn` to its `oac_arn`, clear `TF_VAR_oac_create_environment`, review/apply the bootstrap update, and set repository variable `PAWLOCAL_PRODUCTION_OAC_ARN`. Both environments will then use exact OAC ARNs without wildcard OAC reads or create grants. Repeat temporary selection only for a reviewed replacement. The local Terraform apply exception applies only to the isolated bootstrap state; application infrastructure plans and applies run through GitHub Actions.

The identity stage uses `pawlocal/identity/terraform.tfstate` with branch-trusted plan and protected `identity-apply` roles. During the later recreation work, the IAM bootstrap state may take ownership of development/production frontend publisher roles trusted by GitHub Environments. The development application runtime role `pawlocal-development-dsql-runtime` remains managed by the fullstack app module and is not part of the GitHub publisher-role handoff. Identity Terraform manages only fixed managed-policy attachments on approved role ARNs; its apply role cannot create roles or modify trust, permissions boundaries, or policy documents. Empty resource ARN inputs use nonexistent sentinel ARNs, granting no useful service access. Environment apply roles receive no IAM write permissions.

The legacy combined-stack teardown workflow remains approval-gated in `infrastructure-apply`. The isolated split-environment roles still have no application-resource delete permissions. Backup, HA, restore, and recovery features remain out of this release. Verify immutable subject customization and GitHub Environment protections before publishing role ARNs.

The application environment roots and the separate identity stage that owns runtime and release IAM roles are being handled in the approval-pipeline work. Build each environment foundation without an API deployment, then apply the identity stage, then deploy the API with its reviewed runtime role ARN. The separate environment plan/apply roles do not inherit the legacy combined-state role's destructive permissions. State separation remains tracked by [Issue #112](https://github.com/alanlima/pawlocal/issues/112); the legacy role exists only for the current combined-state workflow until the split roots are deployed.

When the bootstrap IAM policies are independently approved, initialize the root with the existing encrypted, versioned Terraform state bucket and native S3 lockfile. Supply repository identifiers and AWS configuration as local Terraform input variables; do not place access keys or session tokens in Terraform variables or files.

```powershell
$env:PAWLOCAL_TF_STATE_BUCKET = "<existing Terraform state bucket name>"
$env:TF_VAR_terraform_state_bucket_name = $env:PAWLOCAL_TF_STATE_BUCKET
$env:TF_VAR_github_repository = "alanlima/pawlocal"
$env:TF_VAR_github_owner_id = "<immutable GitHub owner ID>"
$env:TF_VAR_github_repository_id = "<immutable GitHub repository ID>"
$env:TF_VAR_route53_zone_id = "<existing Route 53 hosted zone ID>"
$env:TF_VAR_domain_name = "<existing root domain>"
terraform -chdir=infra/terraform/iam-bootstrap init -input=false `
  -backend-config="bucket=$env:PAWLOCAL_TF_STATE_BUCKET" `
  -backend-config="key=pawlocal/iam-bootstrap/terraform.tfstate" `
  -backend-config="region=ap-southeast-2" `
  -backend-config="encrypt=true" `
  -backend-config="use_lockfile=true"
terraform -chdir=infra/terraform/iam-bootstrap plan -input=false -out=iam-bootstrap.tfplan `
  -var="import_existing_frontend_publish_roles=false" `
  -var="import_existing_dsql_service_linked_role=true" `
  -var="manage_github_oidc_provider=false" `
  -var="import_existing_github_oidc_provider=false"
```

Aurora DSQL creates `AWSServiceRoleForAuroraDsql` automatically when its first cluster is created. If the role already exists, include `-var=import_existing_dsql_service_linked_role=true` on the bootstrap plan command; the Terraform import block will adopt the fixed role ARN. If it does not exist, leave the variable false so Terraform creates it. Review the import/create action in the saved plan before applying.

The plan transfer bucket has the deterministic account-specific name `pawlocal-terraform-plans-<AWS account ID>`, so bucket and object ARNs are known while Terraform builds the IAM policies. Check that the name is available in the exact bootstrap plan before applying.

The first bootstrap plan/apply must leave the two existing frontend publisher roles out of the bootstrap state so it can create the legacy plan/apply roles and private plan-transfer bucket without a duplicate-role collision. The Aurora DSQL service-linked role already exists in the current AWS account, so the first plan imports it with `import_existing_dsql_service_linked_role=true`. Keep `import_existing_frontend_publish_roles=false` and both OIDC-provider flags false. Inspect the saved plan to confirm it has no create or import actions for `aws_iam_role.identity_app`; then independently review and apply only that saved plan. The identity app-role ARN output is null for the two frontend roles in this phase.

The first bootstrap apply has completed. Its `legacy_terraform_role_arns` and `plan_transfer_bucket_name` outputs are configured in the GitHub Environments. For the authorized fresh-start teardown, dispatch the protected current-stack workflow with `operation=destroy` and the normal `DESTROY PAWLOCAL` confirmation. The destroy-preparation and full-destroy policy/address validation calls are temporarily commented out so Terraform can remove the app policies and resources needed for the refactor. The final destroy job publishes a value-free resource/action inventory; the exact plan is bound to the run and uploaded, and both `infrastructure-apply` approval gates remain in place.

The bootstrap-owned `pawlocal-legacy-terraform-plan` and `pawlocal-legacy-terraform-apply` roles and their permissions policy are in the separate IAM-bootstrap state and remain available for these operations. The app root releases the shared GitHub OIDC provider with `destroy = false`, leaving it active for GitHub Actions and available for later import into the bootstrap state. The app's development GitHub publisher role is also retained by its existing `destroy = false` block, while its app-managed inline policy is removed with the app stack. The development application runtime role remains app-managed and is deleted by the approved full-destroy plan. No other IAM/bootstrap resources are changed by this teardown.

### Historical planned publisher-role ownership handoff (superseded)

After the environment is recreated, set `TF_VAR_development_frontend_bucket_arn`, `TF_VAR_production_frontend_bucket_arn`, `TF_VAR_development_distribution_arn`, and `TF_VAR_production_distribution_arn` from the existing `environment_targets` output. Use its account ID, frontend bucket names, and distribution IDs to form the exact ARNs. These values keep the imported roles' permissions boundaries aligned with their current inline publish policies. Create a fresh bootstrap plan with `import_existing_frontend_publish_roles=true`, the four inputs set, and both OIDC-provider flags explicitly false. Independently review the two role imports and all trust-policy, permissions-boundary, tag, and description changes, then apply only that saved plan through the separately approved bootstrap procedure. Do not apply a plan with the role-import flag false after the app root has released the roles, or leave the boundary inputs at their pending sentinel values.

```powershell
terraform -chdir=infra/terraform/iam-bootstrap plan -input=false -out=iam-bootstrap-publishers.tfplan `
  -var="import_existing_frontend_publish_roles=true" `
  -var="development_frontend_bucket_arn=$env:TF_VAR_development_frontend_bucket_arn" `
  -var="production_frontend_bucket_arn=$env:TF_VAR_production_frontend_bucket_arn" `
  -var="development_distribution_arn=$env:TF_VAR_development_distribution_arn" `
  -var="production_distribution_arn=$env:TF_VAR_production_distribution_arn" `
  -var="manage_github_oidc_provider=false" `
  -var="import_existing_github_oidc_provider=false"
```

The teardown releases the OIDC provider from the app root with `removed { destroy = false }` and reads it through a data source, so GitHub Actions continues to authenticate. After teardown, set `TF_VAR_manage_github_oidc_provider=true` and `TF_VAR_import_existing_github_oidc_provider=true`, create a fresh bootstrap plan, and confirm it imports the existing provider without creating or replacing it. Review and apply only that exact plan through the approved bootstrap procedure. The bootstrap state will then own the provider for future operations. Do not edit or migrate either state manually.

```powershell
terraform -chdir=infra/terraform/iam-bootstrap plan -input=false -out=iam-bootstrap-oidc.tfplan `
  -var="import_existing_frontend_publish_roles=true" `
  -var="manage_github_oidc_provider=true" `
  -var="import_existing_github_oidc_provider=true"
terraform -chdir=infra/terraform/iam-bootstrap apply -input=false iam-bootstrap-oidc.tfplan
```

For each bootstrap stage, have the independent reviewer inspect that stage's exact plan and digest before applying the matching saved plan: `iam-bootstrap.tfplan`, `iam-bootstrap-publishers.tfplan`, or `iam-bootstrap-oidc.tfplan`. Generate a fresh plan after changing stage inputs; never reuse a plan from another stage. This local apply exception applies only to the isolated IAM bootstrap state and only after independent policy review. All application infrastructure plans and applies run through GitHub Actions. Store each bootstrap plan in a private local workspace and remove it after review. After an approved apply, obtain non-secret outputs with `terraform -chdir=infra/terraform/iam-bootstrap output -json terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json legacy_terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json identity_terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json identity_managed_policy_arns`, and `terraform -chdir=infra/terraform/iam-bootstrap output -raw plan_transfer_bucket_name`; configure the role ARNs and bucket name as Environment variables. Do not print credential values.
