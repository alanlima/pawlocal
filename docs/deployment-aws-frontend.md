# AWS deployment and full-stack release status

The tracked `infra/terraform/` directory is the sole Terraform root and uses the existing `pawlocal/terraform.tfstate` backend key. It preserves the existing root-state production frontend bucket, CloudFront distribution, and DNS record resource addresses, and calls `fullstack/` as a child module with no backend. The child module creates development frontend resources only. Production frontend publishing uses the root's existing bucket, distribution, and deploy-role outputs. The API has its own `api.pawlocal.<domain>` hostname and Terraform-managed Route 53 A record to the API Lightsail static IP; it does not use the frontend CloudFront distribution. No duplicate production frontend bucket, distribution, or alias is declared.

The owner selected Lightsail + Aurora DSQL and approved the MVP budget. The development and production AWS foundation resources are provisioned and converged through Terraform. DSQL app access keys are held in their matching GitHub environment secrets and the requested protected Desktop TXT file; the deployment adapter sends them over SSH stdin to a root-owned runtime credential file on the matching Lightsail instance. They never enter Terraform inputs, outputs, state, plans, repository files, images, user data, or logs. The frontend and backend applications have not yet been deployed. The Terraform change in this workstream adds dedicated, environment-scoped GitHub OIDC roles for temporary Lightsail ingress. Backup, HA, RPO/RTO, restore, recovery, and rollback are deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44). See the [hosting proposal](stage4-hosting-options.md) for cost and compatibility gates.

Issue #43's policy is PR CI, automatic development deployment after successful main CI, and separate manual production promotion of the same backend digest after development verification. The GitHub-hosted deploy runner's observed IPv4 `/32` is added only to the selected Lightsail instance by a targeted plan/apply against the existing Terraform root state; a cleanup plan/apply restores the environment-specific baseline CIDRs. SSH remains restricted, and HTTP/HTTPS rules are retained. Development and production deploy jobs share a non-canceling concurrency group. After environment configuration is complete, a manual dispatch on `main` can run the first GitHub Actions release. No local deployment path is authorized. Development seeding requires explicitly selecting the one-shot `seed_development` dispatch input; automatic main pushes never seed. Telemetry stays disabled for the initial release; enablement is deferred to [Issue #59](https://github.com/alanlima/pawlocal/issues/59). Backup, HA, RPO/RTO, restore, recovery, and rollback are outside MVP scope and deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44).

## Architecture

The build output in `frontend/dist/` is stored in a private S3 bucket. CloudFront serves it through Origin Access Control (OAC), redirects HTTP requests to HTTPS, and returns `index.html` for SPA paths. Route 53 A and AAAA alias records map `pawlocal.<configured-domain>` to the current distribution. For the proposed separate dev/prod sites, the naming convention is `pawlocal-dev.<domain>` and `pawlocal.<domain>` respectively; this convention does not configure or authorize DNS, certificates, or distributions. The existing ACM wildcard certificate is supplied by ARN; ACM certificates used by CloudFront must be in `us-east-1`. Terraform does not request or validate a new certificate.

The root domain, frontend certificate ARN, repository identity, immutable GitHub owner/repository IDs, state bucket, environment-specific baseline SSH CIDRs, and deployment public keys are Terraform inputs. The API subdomain certificate is issued by Caddy; Terraform manages its DNS A record to the Lightsail static IP. Do not commit real `terraform.tfvars`, backend configuration, account identifiers, credentials, or other account-specific values. The tracked `terraform.tfvars.example` contains placeholders only. GitHub Actions receives nonsecret Terraform inputs through environment/repository variables and authenticates to AWS through environment-scoped OIDC roles; private SSH and DSQL keys remain GitHub environment secrets.

Existing production frontend resources continue to receive the root provider tags (`component=frontend`, `workload=static-site`). Child-module application resources use a separate provider alias with `component=fullstack-mvp`, `workload=application`, and `environment=mvp`; tags do not change the existing production resource addresses or state ownership. Some AWS resource types do not expose tag attributes.

## Prerequisites

- Terraform 1.10 or later and AWS credentials with permission for a reviewed Terraform plan/apply against the existing root state.
- The existing, versioned and encrypted S3 bucket reserved for Terraform state. The backend key is `pawlocal/terraform.tfstate` in `ap-southeast-2`; S3 lock files are enabled.
- A public Route 53 hosted zone, an issued ACM certificate in `us-east-1` covering `pawlocal.<configured-domain>` and `pawlocal-dev.<configured-domain>`, owner-selected restricted SSH CIDRs, and review of the integrated plan before any apply.
- The account's GitHub Actions OIDC provider and scoped app-deploy and Terraform-ingress roles. Terraform creates a separate ingress role for each environment. Those roles can write only the shared root state and lock objects and update SSH ports on their corresponding Lightsail instance. By default, Terraform reads the existing account-wide provider. Do not switch ownership of that provider without a separate reviewed decision.
- If DSQL audit-event capture is enabled, an owner-selected audit bucket name and positive retention period are required. Capture defaults off until those choices are made. The alert email destination is also unset.

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

The plan must use the existing root backend and must retain the current production resources at their existing Terraform addresses. Verify the production CloudFront distribution remains frontend-only and that the API Route 53 record targets its Lightsail static IP. Reject any plan that proposes replacing or destroying the existing production bucket, distribution, DNS aliases, or state backend. Do not move, import, remove, or manually edit state bindings. Apply only the exact freshly reviewed plan through Terraform using the existing root state and approved owner authorization. Do not mutate AWS infrastructure through the CLI or console.

## Existing static-site configuration

The following values belong to the existing static-site workflow only; they are not inputs to the Issue #43 full-stack adapter:

| Variable | Value |
| --- | --- |
| `AWS_ROLE_ARN` | Terraform output `github_deploy_role_arn` |
| `AWS_REGION` | Terraform input `aws_region` |
| `FRONTEND_BUCKET` | Terraform output `site_bucket_name` |
| `FRONTEND_DISTRIBUTION_ID` | Terraform output `cloudfront_distribution_id` |

The legacy static-site workflow is retained separately from the full-stack flow and is not evidence that the full application has been deployed. Do not use it as the Issue #43 release path.

The workflows use separate development and production GitHub environments, validate dev health before marking deployment successful, and require production promotion to reference a verified commit and release manifest. They reuse the immutable backend image digest and build the frontend separately for each environment from the selected commit because Vite embeds public Cognito settings. No client secret is embedded. Release records capture commit, image digest, frontend artifact digest, selected database provider, migration runner and identifier, telemetry state, public endpoint health, and a public `GET /api/v1/places` database-query smoke. That query verifies the route returns a valid place-page response and does not claim persistence. An authenticated create-then-read persistence journey remains a live-development gate until a Cognito test identity is available. Terraform outputs expose target configuration, including the per-environment ingress role ARN.

Before deployment, configure each GitHub environment with `PAWLOCAL_DEPLOY_MODE=github-actions`, `PAWLOCAL_DEPLOY_ROLE_ARN`, `PAWLOCAL_TERRAFORM_ROLE_ARN`, `PAWLOCAL_DEPLOY_ADAPTER_PATH`, target host and known-hosts values, frontend/API/Cognito settings, and the environment's DSQL settings. Also configure the nonsecret Terraform variables needed by the ingress workflow: `PAWLOCAL_TF_STATE_BUCKET`, `PAWLOCAL_DOMAIN_NAME`, `PAWLOCAL_CERTIFICATE_ARN`, `PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON`, and `PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON` (the full development/production map). These values must match the approved existing root state and Terraform inputs. Keep SSH private keys and DSQL access keys only in the matching environment secrets.

For each release, the deploy job obtains its public IPv4 address, validates that it is one IPv4 `/32`, and calls `ops/terraform-lightsail-ingress.sh` against the existing S3 backend with a target limited to `module.fullstack.aws_lightsail_instance_public_ports.api["<environment>"]`. The temporary override is environment-scoped. The Terraform resource keeps public ports 80 and 443 in its configuration while adding the runner only to SSH port 22. After deployment, verification, and the optional development seed, an `always()` cleanup step re-assumes the dedicated Terraform ingress role and applies the baseline CIDRs before reporting deployment success. A cleanup failure fails the job and prevents a successful deployment record.

The temporary allow rule has unavoidable recovery limits: GitHub's `always()` step is best effort and cannot run if the hosted runner is forcibly terminated, lost, or unable to authenticate or reach AWS. Terraform's S3 lock protects each plan/apply operation, not the entire interval between opening and restoring the rule; the shared deployment concurrency group serializes these two workflows but does not block a separately run Terraform job. If cleanup cannot complete, the job fails and the owner must inspect the existing root state and use a reviewed Terraform run to restore the baseline before another deployment. No AWS CLI or console firewall edits are permitted.

## Deployment policy

Application deployment and the one-off development seed run through GitHub Actions only. AWS infrastructure changes must be made through Terraform using the existing shared root state; direct AWS CLI or console mutations are not permitted. The reviewed Terraform provisioning run is separate from the Actions release workflow and is required to create the ingress roles and install the host seed helper. The deployment workflow uses targeted Terraform plan/apply against that same state only for temporary SSH ingress and its cleanup.

If `seed_development` is selected on a development `workflow_dispatch`, the workflow verifies through the public `/api/v1/places` endpoint that both Orleigh Park and Whites Hill Reserve are returned. It uploads the names and verification timestamp as a separate `pawlocal-development-seed-verification` artifact. Push-triggered development deployments do not seed or run this content check.

## Full-stack release operation and current blockers

The current code adds two scoped Terraform-ingress roles and changes the shared SSH input to environment-keyed baseline CIDRs. The latest read-only plan against the existing root state showed replacement of both currently unreachable API Lightsail hosts because their `user_data` changes, plus four ingress-role resources and no other resource changes. This plan has not been applied; the existing hosts and role configuration remain unchanged until the reviewed Terraform apply is run. The app deploy job remains gated until the required Terraform resources are provisioned and the owner configures the documented GitHub variables and role ARNs. A `workflow_dispatch` on `main` can execute the full-stack build and deployment after those settings are ready. Development database seeding is separately gated by a one-shot boolean dispatch input, defaulting to false; automatic pushes never seed. Telemetry is off, with enablement deferred to Issue #59; Issue #44 owns deferred backup/HA/recovery/rollback review after MVP cloud deployment.

### Intended production promotion

1. Open GitHub → **Actions** → **Deploy Production** → **Run workflow**.
2. Select the approved `main` ref and enter/select the release commit SHA that has already passed required CI and completed development deployment plus health/smoke verification.
3. Let the workflow validate that the SHA belongs to permitted `main` history, required CI passed, and the same release was successfully verified in development. A free-text SHA alone is not sufficient evidence.
4. Run preflight checks against production configuration and health endpoints. Apply only reviewed DSQL-compatible database migrations when needed. Use expand/contract migrations that remain backward-compatible with the currently deployed application throughout rollout; do not rename/drop columns or tighten constraints until all deployed code versions no longer depend on the old shape. Database recovery and rollback procedures are deferred to Issue #44; stop promotion and escalate if a migration or deployment fails.
5. Deploy the exact backend image digest used in development and the environment-specific frontend built from the same commit. Do not rebuild the backend image for production. Keep production concurrency serialized and do not cancel an active deployment.
6. Run health checks and end-to-end smoke checks against the public production endpoints and confirm the user journey works with production data/API configuration. If checks fail, stop promotion and record the failing checks and deployed identifiers. Do not claim an MVP recovery or rollback guarantee; the recovery review is deferred to Issue #44. Record the commit SHA, backend image digest, frontend artifact/version, selected database provider and migration runner/identifier, health/smoke results, and deployment outcome.

Backup, HA, RPO/RTO, restore, recovery, and rollback procedures are not part of this MVP workflow. They are deferred for review to Issue #44 after the MVP is deployed to cloud.

## Legacy static-site Terraform notes

The following operational notes apply only if the separate static-site Terraform stack is intentionally used. They do not verify or operate the Issue #43 full-stack release:

- Visit the Terraform `site_url` output over HTTPS after CloudFront reports `Deployed` and DNS has propagated.
- Reload a nested place URL directly to verify SPA fallback.
- Inspect Actions logs for any static-site publish activity. Do not print credentials or Terraform variable values in logs.

The legacy static-site workflow is not the MVP full-stack deployment path. Do not use its mock-backed demo behavior as production validation. The current Issue #43 workflows use environment-specific builds with mock mode false and telemetry disabled. API requests target the separate environment API endpoint (`https://api-dev.<domain>/api/v1` or `https://api.<domain>/api/v1`), not a frontend CloudFront `/api/*` behavior. The API allows browser requests only from its matching frontend origin.

## Cost and cleanup

### Estimate (USD/month)

The draft plan creates one private S3 site bucket, one CloudFront distribution, two Route 53 aliases in the existing public hosted zone, and an IAM deploy role. It uses the account's existing OIDC provider by default; creating the provider is optional and controlled by `manage_github_oidc_provider`. There is no always-on compute, NAT gateway, new hosted zone, WAF configuration, logging, or new certificate.

| Scenario | Estimated incremental monthly cost | Assumptions |
| --- | ---: | --- |
| Idle | About $0.00001 | One 208 KB build stored in S3 Standard in Sydney; the backend state bucket and Route 53 zone already exist. |
| Light traffic | About $0.005 | 10,000 S3 GETs (a conservative cache-miss estimate), 3 S3 PUTs, and the same 208 KB bundle. CloudFront viewer traffic remains within the account's shared free allowance of 1 TB and 10 million HTTP(S) requests/month. |

The S3 estimate uses the current AWS Price List for Asia Pacific (Sydney): $0.025/GB-month for first-tier Standard storage, $0.00000044 per GET, and $0.0000055 per PUT. The current CloudFront pay-as-you-go page lists 1 TB of data transfer and 10 million HTTP(S) requests per month in its always-free tier. Those allowances are shared across the AWS account, so other distributions may consume them. If exceeded, CloudFront charges vary by viewer geography; Australia/New Zealand is currently $0.114/GB for the next 9 TB and HTTPS requests are $0.0125 per 10,000. Route 53 alias A/AAAA queries to CloudFront do not incur query charges; the existing hosted-zone charge continues independently. The estimate excludes taxes, changes in AWS prices, and usage outside these assumptions.

Sources: [CloudFront pay-as-you-go pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/), [S3 pricing](https://aws.amazon.com/s3/pricing/), [Route 53 pricing](https://aws.amazon.com/route53/pricing/). Re-check current prices and account-level usage before apply; the project already has a monthly AWS budget, and a budget limit does not prevent charges.

Do not run `terraform destroy` against this shared root: it also owns the existing production frontend and DNS. Any later teardown must use a separately reviewed Terraform change that explicitly preserves those production resources and the existing state backend. Do not move, import, remove, or manually edit state bindings.
