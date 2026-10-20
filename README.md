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

The standalone `infra/terraform/iam-bootstrap` root uses the separate state key `pawlocal/iam-bootstrap/terraform.tfstate`. It creates the GitHub OIDC Terraform plan/apply and recovery roles and a dedicated private bucket for short-lived saved plans. It does not create application resources. No bootstrap plan or apply has been run, and no role ARNs have been published.

Plan roles have no GitHub Environment boundary: they trust the immutable repository subject for `ref:refs/heads/main`, so plan can run before approval. Apply roles trust the protected `development-apply` and `production-apply` GitHub Environments; recovery apply uses `terraform-recovery-apply`. Configure required reviewers and allowed branches on apply Environments. All subjects include immutable GitHub owner and repository IDs; verify that the repository's OIDC subject customization produces these exact claims before using the roles. Store the non-secret plan role ARNs in repository variables `PAWLOCAL_DEVELOPMENT_TERRAFORM_PLAN_ROLE_ARN` and `PAWLOCAL_PRODUCTION_TERRAFORM_PLAN_ROLE_ARN`. Store `PAWLOCAL_TERRAFORM_ROLE_ARN` as the apply-role variable in each protected apply Environment.

The bootstrap root creates a dedicated plan transfer bucket with public access blocked, `BucketOwnerEnforced` object ownership, default AES-256 encryption, versioning, and one-day expiration for current and noncurrent plan objects, plus incomplete multipart upload cleanup. Plan roles can upload only under their environment prefix; matching apply roles can read only that prefix. S3 lifecycle expiration is asynchronous. Workflows must bind the saved plan to repository, environment, run and attempt, commit, and digest, and print only a reviewed sanitized summary. Never log the plan binary/JSON or upload Terraform state snapshots or credentials.

**The GitHub Terraform roles are not deployment-ready.** Their scoped non-destructive service actions are documented in [the IAM policy design](infra/terraform/iam-bootstrap/POLICY_DESIGN.md). Delete/replacement permissions remain absent, so a plan that requires those actions cannot be applied. Lightsail create actions require `Resource: "*"` in AWS authorization and permit any name when the approved PawLocal environment tags are supplied. CloudFront distribution creation requires `TagResource`, so the environment apply roles receive it on the account's `distribution/*` ARN family, with PawLocal project/environment request-tag and approved tag-key conditions. `UpdateDistribution` is also granted on the account's distribution ARN family when existing project/environment tags match the apply role. The owner explicitly accepts the resulting MVP risk: the development role can retag a production distribution as development and then change its full CloudFront configuration; the production role can do the same to development. The bootstrap state manages Aurora DSQL's service-linked role. If AWS already created that role, import it into the bootstrap state before applying that resource. The code-level inventory does not prove live resource names, tags, or state ownership.

CloudFront OAC permissions use a staged handoff because OAC IDs are generated dynamically and AWS provides no tag conditions for them. Set local bootstrap input `oac_create_environment=development` for the first OAC creation. Only that environment's apply role temporarily receives `CreateOriginAccessControl` on `Resource: "*"` and wildcard OAC Get/GetConfig read access for Terraform's create/read cycle. No plan role gets temporary wildcard OAC access; `ListOriginAccessControls` is not granted. After development succeeds through GitHub Actions, retrieve its `oac_arn` output. Before starting the production plan, use the approved local Terraform bootstrap procedure to set `TF_VAR_development_oac_arn` to that ARN and `TF_VAR_oac_create_environment=production`, then review and apply the bootstrap update. Development OAC reads/updates/deletes then use only the dev ARN; only production apply temporarily gets create and wildcard read access. Set repository variable `PAWLOCAL_DEVELOPMENT_OAC_ARN` to the dev ARN for the workflow state guard. After production succeeds through GitHub Actions, set `TF_VAR_production_oac_arn` to its `oac_arn`, clear `TF_VAR_oac_create_environment`, review/apply the bootstrap update, and set repository variable `PAWLOCAL_PRODUCTION_OAC_ARN`. Both environments will then use exact OAC ARNs without wildcard OAC reads or create grants. Repeat temporary selection only for a reviewed replacement. The local Terraform apply exception applies only to the isolated bootstrap state; application infrastructure plans and applies run through GitHub Actions.

The identity stage uses `pawlocal/identity/terraform.tfstate` with branch-trusted plan and protected `identity-apply` roles. The IAM bootstrap state owns the development/production frontend publisher roles, their exact GitHub Environment trust, the development DSQL runtime role, its exact Lightsail and seed-workflow trust, the fixed managed policy documents, and the required permissions boundary. The runtime role is created only after the exact Lightsail `principal_arn` foundation output is supplied. Identity Terraform manages only fixed managed-policy attachments on those bootstrap-owned role ARNs; its apply role cannot create roles or modify trust, permissions boundaries, or policy documents. Empty resource ARN inputs use nonexistent sentinel ARNs, granting no useful service access. After environment foundation outputs exist, update the bootstrap state with exact bucket, distribution, DSQL cluster, and Lightsail principal ARNs before identity applies. Environment apply roles receive no IAM write permissions.

The bootstrap root contains optional exact-resource grants for the protected legacy recovery workflow. They are disabled by default. Destroy grants require exact legacy ARNs/DNS names from a successful sanitized GitHub Actions plan, then an independent check that those values match the reviewed Terraform addresses. The current sanitizer does not expose every exact value, so recovery remains blocked until that output contract is completed. DSQL deletion protection has a separate `recovery-dsql-protection-apply` role with `dsql:UpdateCluster` on only the two exact configured cluster ARNs; its separate exact plan must change only deletion protection. S3 cleanup uses Terraform `force_destroy` and version deletion permissions, with no Object Lock or retention bypass. Backend and saved-plan buckets are excluded. Keep recovery role ARN variables unset until the plan and all resource identifiers are independently reviewed. `iam:GetOpenIDConnectProvider` remains limited to the GitHub provider ARN. Verify immutable subject customization and GitHub Environment protections before publishing role ARNs.

The application environment roots and the separate identity stage that owns runtime and release IAM roles are being handled in the approval-pipeline work. Build each environment foundation without an API deployment, then apply the identity stage, then deploy the API with its reviewed runtime role ARN. Environment plan/apply roles must not receive IAM write permissions. State separation and the approved full-stack recovery plan remain separate gates tracked by [Issue #112](https://github.com/alanlima/pawlocal/issues/112); all acceptance criteria stay open until independent review verifies evidence.

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
terraform -chdir=infra/terraform/iam-bootstrap plan -input=false -out=iam-bootstrap.tfplan
```

Aurora DSQL creates `AWSServiceRoleForAuroraDsql` automatically when its first cluster is created. If the role already exists, include `-var=import_existing_dsql_service_linked_role=true` on the bootstrap plan command; the Terraform import block will adopt the fixed role ARN. If it does not exist, leave the variable false so Terraform creates it. Review the import/create action in the saved plan before applying.

Have the independent reviewer inspect the exact plan and its digest before applying it with `terraform -chdir=infra/terraform/iam-bootstrap apply -input=false iam-bootstrap.tfplan`. This local apply exception applies only to the isolated IAM bootstrap state and only after independent policy review. All application infrastructure plans and applies run through GitHub Actions. Store the bootstrap plan in a private local workspace and remove it after review. After an approved apply, obtain non-secret outputs with `terraform -chdir=infra/terraform/iam-bootstrap output -json terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json identity_terraform_role_arns`, `terraform -chdir=infra/terraform/iam-bootstrap output -json identity_managed_policy_arns`, and `terraform -chdir=infra/terraform/iam-bootstrap output -raw plan_transfer_bucket_name`; do not print credential values. The initial OIDC provider remains data-sourced while the existing root owns it. After the separately reviewed recovery destroy removes that provider, set `-var=manage_github_oidc_provider=true` for the reviewed bootstrap update so this state creates and owns it before environment deployments.
