# AWS deployment: mock-backed frontend

This runbook describes the first PawLocal release: a static React/Vite frontend using seeded mock data. It does not deploy the API, database, or hosted observability stack.

The separately reviewed Stage 4 backend-hosting direction and its remaining DSQL compatibility and credential gate are documented in the [hosting proposal](stage4-hosting-options.md). The owner approved the MVP budget; backup, HA, RPO/RTO, restore, and recovery are deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44). These changes do not expand this static frontend deployment.

Issue #43 records the full-stack policy: PR CI; automatic development deployment after successful main CI; and a separate manually dispatched production promotion selecting a release verified in development. Use `pawlocal-dev.<domain>` for development and `pawlocal.<domain>` for production. This policy is not implemented by this static-site workflow. The current workflow continues to publish the mock-backed frontend to its existing production distribution until the replacement full-stack flow is ready. DSQL compatibility and credentials remain required before selecting that database path. The owner-approved MVP excludes backup, HA, RPO/RTO, restore, recovery, and telemetry work; see Issues #44 and #59.

## Architecture

The build output in `frontend/dist/` is stored in a private S3 bucket. CloudFront serves it through Origin Access Control (OAC), redirects HTTP requests to HTTPS, and returns `index.html` for SPA paths. Route 53 A and AAAA alias records map `pawlocal.<configured-domain>` to the current distribution. For the proposed separate dev/prod sites, the naming convention is `pawlocal-dev.<domain>` and `pawlocal.<domain>` respectively; this convention does not configure or authorize DNS, certificates, or distributions. The existing ACM wildcard certificate is supplied by ARN; ACM certificates used by CloudFront must be in `us-east-1`. Terraform does not request or validate a new certificate.

The root domain, certificate ARN, repository identity, immutable GitHub owner/repository IDs, and AWS region are supplied as local Terraform inputs. GitHub repositories created after July 15, 2026 use immutable numeric IDs in their OIDC subject claim, so the trust policy uses all four repository identity values and remains limited to the `main` branch. Terraform looks up the matching public Route 53 hosted zone from the root domain. Do not commit real `terraform.tfvars`, backend configuration, account identifiers, credentials, or other account-specific values. The tracked `terraform.tfvars.example` contains placeholders only. The backend bucket name is supplied to `terraform init` from the operator's local environment; only the state key is fixed in this repository.

Taggable AWS resources receive common Terraform provider default tags: `costcenter=personal`, `environment=production` by default, `managedby=terraform`, `project=pawlocal`, `component=frontend`, and `workload=static-site`. Tag keys and values are lowercase. Set the `environment` input to `development`, `staging`, or `production` when reusing the configuration. The installed AWS provider does not expose tag attributes for the Route 53 record, CloudFront origin access control, or IAM inline-policy resources; Terraform-only identifiers and nested bucket settings are not independently taggable AWS resources.

## Prerequisites

- Terraform 1.10 or later and AWS CLI credentials with permission to manage the resources declared in `infra/terraform/`.
- The existing, versioned and encrypted S3 bucket reserved for Terraform state. Supply its name locally; the backend key is `pawlocal/terraform.tfstate` in `ap-southeast-2`. S3 lock files are enabled.
- A public Route 53 hosted zone, the ARN of an issued ACM certificate in `us-east-1` covering `pawlocal.<configured-domain>`, and approval of estimated AWS costs before `apply`.
- The account's GitHub Actions OIDC provider and a scoped IAM deploy role are used by Terraform. By default, Terraform looks up the existing account-wide provider. Set `manage_github_oidc_provider=true` only when the account has no provider and this deployment is explicitly meant to create it. The role trusts only the configured repository and `main` branch and can write the site bucket and invalidate this distribution; it cannot change infrastructure or Route 53.

## Initialize and review Terraform

From the repository root in PowerShell:

```powershell
Copy-Item infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
# Edit the ignored local file with the domain, certificate ARN, and repository.
$env:PAWLOCAL_TF_STATE_BUCKET = "<existing Terraform state bucket name>"
Set-Location infra/terraform
terraform init `
  -backend-config="bucket=$env:PAWLOCAL_TF_STATE_BUCKET" `
  -backend-config="key=pawlocal/terraform.tfstate" `
  -backend-config="region=ap-southeast-2" `
  -backend-config="encrypt=true" `
  -backend-config="use_lockfile=true"
terraform fmt -check
terraform validate
terraform plan -out=pawlocal.tfplan
```

Review the plan, including CloudFront distribution, S3 bucket, OIDC provider/role, and Route 53 aliases. With the default `manage_github_oidc_provider=false`, the provider is data-only and must already exist; the plan must not create, replace, or destroy it. Set the flag to `true` only when creating the account-wide provider is needed and approved. Only run `terraform apply pawlocal.tfplan` after explicit cost approval. The state bucket must already exist; this stack never creates or deletes it.

### Migrating an existing Terraform state

Older state may contain `aws_iam_openid_connect_provider.github`. Back up the remote state and confirm the provider URL and ARN in AWS before changing the ownership mode. If Terraform already manages this provider and should continue to, set `manage_github_oidc_provider=true`; the resource address moves to index `[0]` and remains managed. If the provider should be treated as shared/external, first remove only its Terraform state binding with `terraform state rm aws_iam_openid_connect_provider.github`, then keep the flag `false` and run `terraform plan` again. `state rm` does not delete the AWS provider. Review the resulting plan and verify the OIDC provider has no create, replace, or destroy action before any apply. Do not apply a plan that proposes removal of this shared provider.

#### Read-only migration verification

On 2026-10-18, Terraform 1.14.3 with the locked AWS provider planned both ownership paths against the existing deployment state and live AWS resources. No plan was applied.

- With `manage_github_oidc_provider=true`, Terraform recognized the move from `aws_iam_openid_connect_provider.github` to `aws_iam_openid_connect_provider.github[0]`. The plan reported **0 to add, 0 to change, 0 to destroy**; the deployment role also had no action.
- For the shared/external mode, the remote state was pulled to a disposable local copy. The provider binding was removed from that local copy only, then a plan with `manage_github_oidc_provider=false` reported **no changes**. The existing provider was read as a data source and the deployment role had no action.

The state pull, temporary local backend, and local state removal did not write to the remote state or mutate AWS resources. Repeat these checks against the target account and state immediately before a real ownership migration; do not infer that another environment's state has the same ownership.

## Configure GitHub Actions

After applying Terraform, set these repository Actions **variables** (not secrets):

| Variable | Value |
| --- | --- |
| `AWS_ROLE_ARN` | Terraform output `github_deploy_role_arn` |
| `AWS_REGION` | Terraform input `aws_region` |
| `FRONTEND_BUCKET` | Terraform output `site_bucket_name` |
| `FRONTEND_DISTRIBUTION_ID` | Terraform output `cloudfront_distribution_id` |

No long-lived AWS access key is used. Only the production deployment job has `id-token: write`; GitHub OIDC trusts the configured repository's `main` branch. The pull request workflow runs format/lint, unit tests, and a production build with `VITE_USE_MOCK_BACKEND=true` when `frontend/**` or its workflow changes. Superseded pull request checks are canceled per PR. The separate production deployment workflow runs the same checks and build on `main` pushes that change `frontend/**`, then publishes the built assets and invalidates CloudFront. It can also be run manually from `main` for the initial publish after infrastructure is applied and later republishing. Changes outside the frontend and deployment workflow do not trigger automatic deployment. This describes the current mock-backed static-site workflow only; it is not the Issue #43 full-stack release flow.

Issue #43's full-stack flow requires separate development and production GitHub environments, endpoints, secrets, and deployment credentials; successful PR/main CI; automatic dev deployment and health/smoke verification; and a manual production dispatch that validates a main-history commit with successful CI and a verified dev deployment. Promote the same immutable backend image digest. Vite configuration is build-time today, so production must either receive public runtime configuration or use a controlled environment-specific build from the same tested commit; never embed secrets in browser assets. Serialize production promotions without canceling an active deploy and record commit/image/frontend/migration identifiers and results. Backup, HA, and recovery/rollback procedures are deferred to Issue #44; the MVP must not claim those guarantees.

## Proposed full-stack operator sequence (not yet actionable)

These are the intended operator steps for Issue #43 after DSQL compatibility/credentials are validated and the deployment targets, credentials, and workflows are implemented. The owner has approved the MVP budget. **They cannot be run today:** the required full-stack environments and `Deploy Production` workflow do not exist, and the current static frontend workflow is a separate mock-backed release. Treat that existing mock-backed production deployment as a temporary transition; change or disable it before claiming the Issue #43 full-stack promotion policy is implemented, so it cannot continue publishing the demo bundle as the production application. Backup/HA/recovery procedures and telemetry remain out of the MVP scope.

### Production promotion

1. Open GitHub → **Actions** → **Deploy Production** → **Run workflow**.
2. Select the approved `main` ref and enter/select the release commit SHA that has already passed required CI and completed development deployment plus health/smoke verification.
3. Let the workflow validate that the SHA belongs to permitted `main` history, required CI passed, and the same release was successfully verified in development. A free-text SHA alone is not sufficient evidence.
4. Run preflight checks against production configuration and health endpoints. Apply only reviewed DSQL-compatible database migrations when needed. Use expand/contract migrations that remain backward-compatible with the currently deployed application throughout rollout; do not rename/drop columns or tighten constraints until all deployed code versions no longer depend on the old shape. Database recovery and rollback procedures are deferred to Issue #44; stop promotion and escalate if a migration or deployment fails.
5. Deploy the exact backend image digest used in development and the approved frontend artifact/version for that commit. Do not rebuild the backend image for production. Keep production concurrency serialized and do not cancel an active deployment.
6. Run health checks and end-to-end smoke checks against the public production endpoints and confirm the user journey works with production data/API configuration. If checks fail, stop promotion and record the failing checks and deployed identifiers. Do not claim an MVP recovery or rollback guarantee; the recovery review is deferred to Issue #44. Record the commit SHA, backend image digest, frontend artifact/version, migration version, health/smoke results, and deployment outcome.

### Deferred manual rollback design (Issue #44)

1. Stop further promotion and identify the previous known-good frontend artifact/version and backend image digest from deployment evidence.
2. Redeploy those exact previous artifacts through the approved production deployment mechanism; do not rebuild them.
3. Do **not** automatically reverse database migrations. Confirm the current schema remains compatible with the previous application release; use only backward-compatible migration sequencing. If compatibility is uncertain, stop and follow the reviewed database recovery procedure rather than attempting an automatic downgrade.
4. Re-run health and end-to-end smoke checks against the public production endpoints, verify the user-facing journey, and record the rollback artifacts, schema/migration version, checks, and result. Keep the failed release and incident evidence for diagnosis.

This rollback procedure is deferred to Issue #44 and is not an Issue #43 MVP acceptance criterion. The production workflow and deployment targets remain unimplemented until DSQL compatibility, configuration, and CI/dev verification are complete.

## Verify and operate

- Visit the Terraform `site_url` output over HTTPS after CloudFront reports `Deployed` and DNS has propagated.
- Reload a nested place URL directly to verify SPA fallback.
- Confirm the frontend displays seeded demo data and has no backend dependency.
- Inspect GitHub Actions logs for the build, S3 sync, and invalidation result. Do not print credentials or Terraform variable values in logs.

For the first publish after the infrastructure apply, run **Frontend production deployment** manually from the GitHub Actions tab with `main` selected.

Main-branch deployment workflow runs share a production concurrency group with `queue: max`, so up to 100 pending deployments wait in order and an active S3 sync or CloudFront invalidation is not canceled. This queue is separate from pull request checks, which cancel superseded runs. GitHub documents that pending-run order is based on when a run starts waiting on the concurrency group, not strictly on dispatch time, and cancels runs beyond the 100-run queue limit. Each successful merge that changes `frontend/**` deploys automatically to the same distribution. Rollback by reverting the frontend change and merging the revert; the normal workflow republishes the prior source state.

## Cost and cleanup

### Estimate (USD/month)

The draft plan creates one private S3 site bucket, one CloudFront distribution, two Route 53 aliases in the existing public hosted zone, and an IAM deploy role. It uses the account's existing OIDC provider by default; creating the provider is optional and controlled by `manage_github_oidc_provider`. There is no always-on compute, NAT gateway, new hosted zone, WAF configuration, logging, or new certificate.

| Scenario | Estimated incremental monthly cost | Assumptions |
| --- | ---: | --- |
| Idle | About $0.00001 | One 208 KB build stored in S3 Standard in Sydney; the backend state bucket and Route 53 zone already exist. |
| Light traffic | About $0.005 | 10,000 S3 GETs (a conservative cache-miss estimate), 3 S3 PUTs, and the same 208 KB bundle. CloudFront viewer traffic remains within the account's shared free allowance of 1 TB and 10 million HTTP(S) requests/month. |

The S3 estimate uses the current AWS Price List for Asia Pacific (Sydney): $0.025/GB-month for first-tier Standard storage, $0.00000044 per GET, and $0.0000055 per PUT. The current CloudFront pay-as-you-go page lists 1 TB of data transfer and 10 million HTTP(S) requests per month in its always-free tier. Those allowances are shared across the AWS account, so other distributions may consume them. If exceeded, CloudFront charges vary by viewer geography; Australia/New Zealand is currently $0.114/GB for the next 9 TB and HTTPS requests are $0.0125 per 10,000. Route 53 alias A/AAAA queries to CloudFront do not incur query charges; the existing hosted-zone charge continues independently. The estimate excludes taxes, changes in AWS prices, and usage outside these assumptions.

Sources: [CloudFront pay-as-you-go pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/), [S3 pricing](https://aws.amazon.com/s3/pricing/), [Route 53 pricing](https://aws.amazon.com/route53/pricing/). Re-check current prices and account-level usage before apply; the project already has a monthly AWS budget, and a budget limit does not prevent charges.

To remove this deployment, first disable/remove the GitHub deployment workflow or role variables, then run `terraform destroy` from this directory after reviewing the plan. The site bucket is not force-emptied, so remove its objects intentionally before destroying it. The pre-existing Terraform state bucket and its `pawlocal/terraform.tfstate` object are outside this stack and must be preserved unless the project owner separately requests state removal.
