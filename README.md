# PawLocal

PawLocal is a community-maintained directory of dog-friendly places across South East Queensland, from the Gold Coast to the Sunshine Coast.

## Project status

**Stages 2, 3, and 3.1 are complete and reviewed. Stage 4 is in progress.** Issue #43 CI/CD workflows define automatic development deployment after successful `main` CI and separate manual production promotion of the same development-verified backend image digest. The owner selected Lightsail + Aurora DSQL and one long-term application IAM key per environment; GitHub deployment uses scoped OIDC roles. Issue #62 adds the adapter and Terraform target, which still require review and deployment configuration. DSQL runtime compatibility requires live validation. No AWS resources or app keys have been provisioned and no full-stack deployment has occurred. Telemetry is disabled for the initial release; enablement is deferred to [Issue #59](https://github.com/alanlima/pawlocal/issues/59). Backup, HA, RPO/RTO, restore, recovery, and rollback are out of MVP scope and deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44). CI validates frontend and backend changes, the combined local Compose stack, and Terraform configuration. Mock data is selected only when `VITE_USE_MOCK_BACKEND=true`; the combined Compose stack selects the HTTP adapter. Place access and facility details are not represented as verified facts. See [local development setup](frontend/README.md).

Issue #43 records the full-stack release policy: PR CI, automatic deployment of successful main releases to development, and a separate manually dispatched production promotion of a release already verified in development. The Issue #62 adapter and Terraform target implement the selected Lightsail + DSQL direction, but remain unreviewed/unconfigured and DSQL runtime validation is incomplete. The existing static-site Terraform configuration is not the full-stack deployment target. See the [AWS deployment runbook](docs/deployment-aws-frontend.md), [hosting proposal](docs/stage4-hosting-options.md), and [decision log](docs/decisions.md).

## Project documentation

- [Product specification](product-spec.md)
- [OpenAPI contract](openapi.yaml)
- [Architecture](docs/architecture.md)
- [Implementation plan and issue proposals](docs/implementation-plan.md)
- [Agent workflow](docs/agent-workflow.md)
- [Model policy](docs/model-policy.md)
- [Decisions](docs/decisions.md)
- [Testing approach](docs/testing.md)
- [AWS frontend deployment runbook](docs/deployment-aws-frontend.md)
- [AI usage report](docs/ai-usage-report.md)

## Planned stack

React, TypeScript, Vite and Tailwind CSS; Python, FastAPI and Pydantic; PostgreSQL with SQLAlchemy 2 and Alembic; Docker Compose; and OpenTelemetry with Grafana, Prometheus, Loki and Tempo. Local Compose uses PostgreSQL. The owner selected Lightsail + Aurora DSQL with per-environment IAM app keys; DSQL still requires live compatibility validation and deployment setup. Hosted telemetry is disabled for the initial release; backup, HA and recovery are deferred. The MVP budget is approved; no cloud resources or app keys have been provisioned and deployment has not occurred.

## Backend development

Stage 3 backend setup, migration, API, and test instructions are in [backend/README.md](backend/README.md). Protected API operations validate Cognito access tokens; no Cognito or other AWS resources are provisioned in this stage.

## Frontend service mode

The frontend uses `MockPlaceService` only when `VITE_USE_MOCK_BACKEND=true`. When the toggle is false or unset, it selects the typed `HttpPlaceService` and uses `VITE_API_BASE_URL` (default `/api/v1`). Vite's development server proxies that path to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`); set the target to `http://backend:8000` in Compose. Cloud releases use separate HTTPS API hosts (`api-dev.<domain>` and `api.<domain>`), while CloudFront serves frontend assets only. A failed or unavailable API remains an HTTP error and never silently switches to mock data. The checked-in `.env.example` opts into mock mode for the local demo.

HTTP-mode authentication is a host integration seam, not a PawLocal sign-in flow. The host can inject `window.pawLocalAuth` before the app loads with `getAccessToken()` returning the current Cognito access token (sync or async), and optional `signIn()`/`signOut()` callbacks. The frontend requests a fresh token for each API call, sends it only as a Bearer header, and does not persist it. Hosts own authentication UX and token refresh. Without the host provider, protected actions report that authentication is unavailable; mock demo-member mode never authenticates HTTP requests. See [frontend/README.md](frontend/README.md#host-authentication-integration) for the interface contract.

## Development

For the combined local frontend, API, PostgreSQL and observability stack, first copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). The example contains a clearly local-only PostgreSQL password placeholder; keep `.env` out of version control and replace the placeholder for your local environment. Compose requires `PAWLOCAL_POSTGRES_PASSWORD` and has no built-in credential fallback. Then run `docker compose up --build -d` from the repository root. Open PawLocal at <http://localhost:5173>, Grafana at <http://localhost:3000>, and the API health endpoint at <http://localhost:8000/health>. See [frontend README](frontend/README.md) and [backend README](backend/README.md) for ports, health checks, privacy, synthetic failures, shutdown, migrations and tests. All local Compose services bind to localhost; running the local stack requires no cloud resources.

## AWS Terraform IAM bootstrap

The standalone `infra/terraform/iam-bootstrap` root uses the separate state key `pawlocal/iam-bootstrap/terraform.tfstate`. Its first reviewed Terraform apply created environment Terraform roles, dedicated legacy combined-state plan/apply roles, and a private bucket for short-lived saved plans, and imported the existing DSQL service-linked role. Their non-secret outputs are configured in the GitHub Environments. The two frontend publisher roles remain to be imported after the combined app root releases them with `destroy = false`; the shared GitHub OIDC provider transfer is a later separate stage. The bootstrap state does not create application resources.

The legacy operations workflow assumes `pawlocal-legacy-terraform-plan` from GitHub Environment `infrastructure-plan` and `pawlocal-legacy-terraform-apply` from `infrastructure-apply`. Configure these non-secret Environment variables only after the approved local bootstrap apply: `PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN` in `infrastructure-plan`, `PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN` in `infrastructure-apply`, and `PAWLOCAL_TERRAFORM_PLAN_BUCKET` in both Environments. Also configure `AWS_REGION`, `PAWLOCAL_AWS_ACCOUNT_ID`, `PAWLOCAL_TF_STATE_BUCKET`, `PAWLOCAL_DOMAIN_NAME`, and `PAWLOCAL_CERTIFICATE_ARN` as Environment variables in both Environments. Restrict both Environments to the protected `main` branch; require reviewers on `infrastructure-apply`. The workflow uses GitHub OIDC, checks the assumed account before Terraform, and configures the action's supported allowed-account guard. No static AWS access-key secrets are used.

The plan and apply roles transfer the exact saved plan and metadata through the bootstrap-owned S3 bucket under `plans/legacy/<run-id>/<attempt>/<stage>/`. The bucket blocks public access, enforces bucket-owner object ownership, encrypts with AES-256, versions objects, and expires current and noncurrent objects after one day. Only the plan role can upload under this prefix; only the apply role can read it. The saved plan digest and metadata remain bound to the repository, Environment, run and attempt, commit, state key, and AWS account. Never log plan contents or upload Terraform state snapshots or credentials.

The legacy combined-stack apply role can mutate application resources in the current combined root and destroy them through the explicitly approved teardown workflow. Most permissions target PawLocal bucket, Lightsail, IAM role, DSQL cluster, Cognito pool, and Route 53 scopes. **CloudFront remains a documented MVP exception:** its distribution IDs are generated, current distributions lack ownership tags, and CreateDistribution requires `Resource: "*"`; consequently the role can create distributions and update/delete any CloudFront distribution in this AWS account. OAC identifiers are generated and cannot be name-scoped, so OAC management is account-wide. Lightsail create APIs also require `Resource: "*"` and the current service resource does not pass tags. These permissions are limited to the named actions needed by the current Terraform root, but they carry account-level impact and must be reviewed before bootstrap apply. This policy does not grant AdministratorAccess or add backup, recovery, or incident-response permissions. The split development/production roles retain their separate-state permissions and do not inherit this legacy role's delete scope.

CloudFront OAC permissions use a staged handoff because OAC IDs are generated dynamically and AWS provides no tag conditions for them. Set local bootstrap input `oac_create_environment=development` for the first OAC creation. Only that environment's apply role temporarily receives `CreateOriginAccessControl` on `Resource: "*"` and wildcard OAC Get/GetConfig read access for Terraform's create/read cycle. No plan role gets temporary wildcard OAC access; `ListOriginAccessControls` is not granted. After development succeeds through GitHub Actions, retrieve its `oac_arn` output. Before starting the production plan, use the approved local Terraform bootstrap procedure to set `TF_VAR_development_oac_arn` to that ARN and `TF_VAR_oac_create_environment=production`, then review and apply the bootstrap update. Development OAC reads/updates/deletes then use only the dev ARN; only production apply temporarily gets create and wildcard read access. Set repository variable `PAWLOCAL_DEVELOPMENT_OAC_ARN` to the dev ARN for the workflow state guard. After production succeeds through GitHub Actions, set `TF_VAR_production_oac_arn` to its `oac_arn`, clear `TF_VAR_oac_create_environment`, review/apply the bootstrap update, and set repository variable `PAWLOCAL_PRODUCTION_OAC_ARN`. Both environments will then use exact OAC ARNs without wildcard OAC reads or create grants. Repeat temporary selection only for a reviewed replacement. The local Terraform apply exception applies only to the isolated bootstrap state; application infrastructure plans and applies run through GitHub Actions.

The identity stage uses `pawlocal/identity/terraform.tfstate` with branch-trusted plan and protected `identity-apply` roles. After the staged ownership handoff, the IAM bootstrap state owns the development/production frontend publisher roles, their exact GitHub Environment trust, the development DSQL runtime role, its exact Lightsail and seed-workflow trust, the fixed managed policy documents, and the required permissions boundary. The runtime role is created only after the exact Lightsail `principal_arn` foundation output is supplied. Identity Terraform manages only fixed managed-policy attachments on those bootstrap-owned role ARNs; its apply role cannot create roles or modify trust, permissions boundaries, or policy documents. Empty resource ARN inputs use nonexistent sentinel ARNs, granting no useful service access. After environment foundation outputs exist, update the bootstrap state with exact bucket, distribution, DSQL cluster, and Lightsail principal ARNs before identity applies. Environment apply roles receive no IAM write permissions.

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

The first bootstrap apply has completed. Its `legacy_terraform_role_arns` and `plan_transfer_bucket_name` outputs are configured in the GitHub Environments. For teardown, dispatch the protected current-stack workflow with `operation=destroy`, the normal `DESTROY PAWLOCAL` confirmation, and the default-off `allow_expected_destroy_preparation_changes=true` input only with the exact typed confirmation `ACCEPT EXPECTED TEARDOWN PREPARATION CHANGES`. This permits the owner-approved app policy, S3, and DSQL preparation updates through the normal `infrastructure-apply` approval gate. That run applies only the exact reviewed preparation plan and intentionally stops before creating a full-destroy plan.

The preparation plan also releases the two publisher roles from the combined app state with `destroy = false` and leaves the AWS roles and their inline policies in place. Before full destroy, create a fresh IAM-bootstrap plan with `import_existing_frontend_publish_roles=true` and the four exact frontend bucket/distribution ARN inputs below. Independently review and apply that saved plan through the separately approved bootstrap procedure. This imports role trust and boundary ownership into the bootstrap state while the combined app root continues to own inline publisher policies. Then dispatch the protected current-stack workflow again with the bypass disabled (its default), so a fresh full-destroy plan is summarized, digest-bound, and held at the separate `infrastructure-apply` approval gate. The app root continues to manage the shared GitHub OIDC provider during this stage.

Next set `TF_VAR_development_frontend_bucket_arn`, `TF_VAR_production_frontend_bucket_arn`, `TF_VAR_development_distribution_arn`, and `TF_VAR_production_distribution_arn` from the existing `environment_targets` output. Use its account ID, frontend bucket names, and distribution IDs to form the exact ARNs. These values keep the imported roles' permissions boundaries aligned with their current inline publish policies. Create a fresh bootstrap plan with `import_existing_frontend_publish_roles=true`, the four inputs set, and both OIDC-provider flags explicitly false. Independently review the two role imports and all trust-policy, permissions-boundary, tag, and description changes, then apply only that saved plan through the separately approved bootstrap procedure. Do not apply a plan with the role-import flag false after the app root has released the roles, or leave the boundary inputs at their pending sentinel values.

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

The OIDC-provider state transfer is a separate later bootstrap operation after the publisher-role import. First make a separate reviewed Terraform change that releases the provider from the app root with `removed { destroy = false }` and reads it through a data source; apply that exact plan through the protected GitHub Actions environment. Then set `TF_VAR_manage_github_oidc_provider=true` and `TF_VAR_import_existing_github_oidc_provider=true`, create a fresh bootstrap plan, and confirm it imports the existing provider ARN without creating or replacing the provider. Review and apply only that exact bootstrap plan using local higher-privilege credentials. The bootstrap state will retain the provider when the app stack is later destroyed. Do not edit or migrate either state manually.

```powershell
terraform -chdir=infra/terraform/iam-bootstrap plan -input=false -out=iam-bootstrap-oidc.tfplan `
  -var="import_existing_frontend_publish_roles=true" `
  -var="manage_github_oidc_provider=true" `
  -var="import_existing_github_oidc_provider=true"
terraform -chdir=infra/terraform/iam-bootstrap apply -input=false iam-bootstrap-oidc.tfplan
```

For each bootstrap stage, have the independent reviewer inspect that stage's exact plan and digest before applying the matching saved plan: `iam-bootstrap.tfplan`, `iam-bootstrap-publishers.tfplan`, or `iam-bootstrap-oidc.tfplan`. Generate a fresh plan after changing stage inputs; never reuse a plan from another stage. This local apply exception applies only to the isolated IAM bootstrap state and only after independent policy review. All application infrastructure plans and applies run through GitHub Actions. Store each bootstrap plan in a private local workspace and remove it after review. After an approved apply, obtain non-secret outputs with `terraform -chdir=infra/terraform/iam-bootstrap output -json terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json legacy_terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json identity_terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json identity_managed_policy_arns`, and `terraform -chdir=infra/terraform/iam-bootstrap output -raw plan_transfer_bucket_name`; configure the role ARNs and bucket name as Environment variables. Do not print credential values.
