# AWS deployment and full-stack release status

The tracked `infra/terraform/` directory is the sole Terraform root and uses the existing `pawlocal/terraform.tfstate` S3 backend. It retains the existing production frontend bucket, CloudFront distribution, DNS records, and account GitHub OIDC provider in the same state. The `fullstack/` module has no backend of its own. Development and production APIs use separate Lightsail Container Services and Aurora DSQL clusters. Both frontend sites use private S3 buckets behind CloudFront Origin Access Control (OAC); visitors use the public CloudFront-backed domain rather than direct S3 URLs.

The owner accepted the Lightsail Container Service design through Issue #75 and explicitly authorized its state-backed AWS apply on 2026-10-19 after reviewing the estimated USD $50/month container cost before other stack costs and transfer. The migration replaced the Lightsail VM/static-IP API path with container services, managed endpoint TLS, Route 53 CNAME records, public digest-pinned GHCR images, and Terraform-managed deployment versions. Both Aurora DSQL clean-install baselines are recorded in the `pawlocal` schema and both API health routes and deployment digests are verified. Database-backed place queries still return HTTP 500, so live DSQL runtime compatibility, credential refresh, and the database query smoke criterion remain open. Two unused CLI-created DSQL access keys were deleted after CloudTrail and IAM checks.

## AWS infrastructure ownership rule

Terraform configuration and the existing shared Terraform state are the only mechanism for creating, changing, replacing, or deleting AWS infrastructure. This covers compute and app deployments, databases, identity, DNS, certificates, networking, IAM, storage, and monitoring. AWS console, CLI, SDK, shell, and bootstrap scripts must not mutate infrastructure or Terraform state. Do not manually edit, import, or remove state bindings. CI may build and publish immutable artifacts; any AWS-side application deployment must be represented by a Terraform resource in the shared state. Runtime secrets must not be stored in Terraform state. An infrastructure migration requires a complete reviewed plan and explicit cost/provisioning approval.

The frontend publisher uses AWS CLI only for application artifact operations (`s3 sync`, release archive upload, and CloudFront invalidation). It does not create or configure AWS resources. Backend container deployments use `aws_lightsail_container_service_deployment_version` through the existing Terraform root state.

### Shell and CLI mutation-path audit

The implementation's AWS CLI calls were reviewed. `s3 sync` and `s3 cp` publish frontend release artifacts, `cloudfront create-invalidation` refreshes the frontend cache, and `lightsail get-container-services` is a read-only post-deployment check. None creates, changes, or deletes AWS infrastructure. The backend deployment script applies a saved Terraform plan that is rejected unless it changes only the selected environment's stateful Lightsail deployment-version resource.

The Terraform release role is deliberately limited to Terraform state access, planning reads, and deployment of its selected Lightsail container service. It cannot create IAM roles, modify DSQL cluster policies, or connect as a DSQL administrator. Development DSQL role mappings are database objects rather than AWS resources, so Terraform does not execute the bootstrap from CI. The `terraform_data.app_dsql_role` resource records only the intended cluster, principal, and database-role inputs; it cannot observe whether SQL mappings match and has no provisioner. After an independently reviewed, development-only Terraform plan is applied by the authorized local operator, run `ops/bootstrap-development-dsql-role.ps1` from the repository root with the backend virtual environment installed. The idempotent helper maps the customer-account runtime role to the app database role and revokes the prior direct Lightsail-principal mapping. The script uses Terraform outputs and the operator AWS identity; it verifies the AWS account matches the managed account and does not change AWS infrastructure or Terraform state. Production remains unchanged during development validation. The prior CLI-created DSQL access keys were removed, and both legacy app users were verified to have no access keys on 2026-10-19.

## Architecture

The frontend remains a private S3 origin behind CloudFront OAC with HTTPS, SPA fallback, and Route 53 alias records. The API is served directly by the Lightsail Container Service public endpoint; Route 53 CNAME records map `api-dev.<domain>` and `api.<domain>` to its generated hostname. Terraform creates domain-validation records, and Lightsail manages the endpoint certificate. Frontend and API origins remain separate.

### Frontend access verification (2026-10-19)

Both frontend buckets have all four S3 Block Public Access settings enabled. Production's bucket policy grants `s3:GetObject` only to its CloudFront distribution OAC; `https://pawlocal.alanlima.cloud/` returned HTTP 200. The development bucket has the same CloudFront-only policy but contains no frontend objects, so `https://pawlocal-dev.alanlima.cloud/` currently returns HTTP 403. Do not make the bucket public to resolve this: publish the development frontend through **Actions → Full-stack release to development → Run workflow** on `main`, after the Issue #75 workflow changes are reviewed and merged.

Two dispatches against the current `main` workflow stopped before the S3 sync because that workflow still tries to assume the removed `pawlocal-development-terraform-ingress` role. The development and production `PAWLOCAL_TERRAFORM_ROLE_ARN` environment variables now point to the scoped `terraform-deploy` roles created by the migration. The Issue #75 branch removes the obsolete SSH-ingress path; rerun the workflow after that change is on `main`. The failed runs did not publish files or change the bucket's access policy.

Each backend image reference is pinned to a public GHCR SHA-256 digest. Development deploys after successful main CI; production is manually promoted only after development verification and uses the same backend digest. The workflow builds the frontend separately per environment because Vite embeds public Cognito settings. Telemetry remains disabled. The container deployment workflow reads both environment image digests from Terraform outputs, updates only the selected environment, creates a full plan, and refuses to apply if any other Terraform resource changes. Initial infrastructure migration is therefore a separate reviewed operation against the existing state. Terraform outputs the environment-scoped release role ARNs as `environment_targets[*].terraform_deploy_role_arn`.

The selected container sizing defaults are development `micro` (1 GiB) and production `medium` (2 GiB), scale one each. The API image and runtime configuration contain no AWS access keys or other secrets. Terraform records the image/deployment configuration; no CLI deployment command is used.

## Prerequisites

- The existing versioned, encrypted state bucket and key `pawlocal/terraform.tfstate` in `ap-southeast-2`, with S3 lock files enabled.
- A public Route 53 zone, the existing CloudFront ACM certificate in `us-east-1`, repository identity/immutable GitHub IDs, and the environment-scoped OIDC roles.
- Public GHCR access to `ghcr.io/alanlima/pawlocal-api`.
- The read-only integrated migration plan review recorded below. Regenerate and review a fresh plan before any apply; it must still preserve unrelated production frontend resources and state addresses and replace only the approved VM/static-IP path plus required deployment identity/DNS resources.
- Live DSQL service-principal/database-role validation before production promotion. Do not treat offline tests or a Terraform plan as proof of runtime DSQL connectivity.

## Initialize and review Terraform

From PowerShell at the repository root:

```powershell
Copy-Item infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
# Set the domain, certificate ARN, repository identity and other required values.
$env:PAWLOCAL_TF_STATE_BUCKET = "<existing Terraform state bucket name>"
Set-Location infra/terraform
terraform init `
  -backend-config="bucket=$env:PAWLOCAL_TF_STATE_BUCKET" `
  -backend-config="key=pawlocal/terraform.tfstate" `
  -backend-config="region=ap-southeast-2" `
  -backend-config="encrypt=true" `
  -backend-config="use_lockfile=true"
terraform fmt -check -recursive
terraform validate
terraform plan -out=pawlocal.tfplan
```

Review the complete state-backed plan. Reject unrelated replacement/deletion, production frontend resource address changes, or an incorrect API DNS/TLS target. Apply only the exact reviewed plan through Terraform after the required cost/provisioning authorization. Never run `terraform destroy` against this shared root.

### Issue #75 applied migration and verification (2026-10-19)

The initial fresh plan was generated against the existing shared S3 state using the Sydney region, current public DNS zone and CloudFront certificate, and a digest-pinned image from a successful main release. It proposed **14 creates, 16 deletes, 2 replacements, 2 in-place updates, and 2 data reads**. The owner authorized applying the reviewed migration, and Terraform applied it through the shared root state. A first attempt stopped on a Lightsail public-port API error and a certificate-name collision. After refreshing state and using migration-versioned certificate names, a fresh plan completed the infrastructure migration. The DSQL role bootstrap then failed because its configured Python environment lacked a transitive AWS SDK dependency; a new environment installed from the backend project dependencies completed both role mappings. A final fresh Terraform plan reported no changes. Saved plans and JSON remain outside the repository and are snapshots only; regenerate before any later apply.

The 16 deletions are the two Lightsail VMs, public-port configurations, static IPs and attachments, IAM app users and their DSQL policies, and temporary-ingress roles and policies. The 14 creates are the two container services, deployments, Lightsail certificates, certificate-validation DNS records, DSQL cluster policies, and environment-scoped Terraform deployment roles and policies. The two initial `terraform_data.app_dsql_role` replacements reran the idempotent database-role mapping helper during migration. The historical runtime-engine code fingerprint no longer triggers that bootstrap; cluster, service-principal, role, or bootstrap-helper changes still do. The two API DNS updates switch each old A record to its service CNAME; the pinned AWS provider plans this as a record update, which sends a delete-old/create-new change batch for the old and new record types.

The apply preserved the existing production frontend bucket, CloudFront distribution, frontend DNS aliases, state backend, account OIDC provider, DSQL clusters, and Cognito pools/clients. It removed the two API VMs, their public-port configurations and static IPs, the legacy app IAM users/policies, and temporary-ingress roles/policies. It created both container services and active deployment versions using the same image digest, `sha256:cc54cd9dab3b0e2210ad07e8f01d3e4dc9b0e4036a9ff826661e046f29598873`, plus Lightsail certificates, validation records, DSQL cluster policies, and scoped Terraform deployment roles. Both public `/health` routes returned HTTP 200. Both `/api/v1/places?limit=1` queries returned HTTP 500, so DSQL runtime compatibility, credential refresh, and the database-backed smoke criterion remain unverified. The migration was authorized in the owner’s Issue #75 comment. The pinned AWS provider's Route 53 record update path batches deletion of the prior record type and creation of the new type in one change batch ([provider v6.69.1 source](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/internal/service/route53/record.go#L3399-L3422)).

## GitHub release configuration

Development and production environments provide `AWS_REGION`, `PAWLOCAL_DEPLOY_ROLE_ARN`, `PAWLOCAL_TERRAFORM_ROLE_ARN`, `PAWLOCAL_TF_STATE_BUCKET`, `PAWLOCAL_DOMAIN_NAME`, `PAWLOCAL_CERTIFICATE_ARN`, frontend bucket/distribution IDs, API health/public URLs, DSQL nonsecret configuration, and public Cognito settings. The Terraform role needs access to the existing state and the reads/actions required to plan and deploy only the environment's Lightsail container deployment. The frontend role is limited to publishing frontend artifacts and invalidating its distribution. Do not configure SSH private keys or DSQL access-key secrets for these workflows.

The release script uses the Terraform state output as the source of the other environment's image digest. It plans with the target environment's release manifest, validates that the plan changes only that environment's `aws_lightsail_container_service_deployment_version` and contains the exact selected digest, then applies that exact saved plan. A pending infrastructure migration or any unrelated drift causes the release to fail closed; review and resolve it separately.

Public verification checks the frontend HTML, API health endpoint, and a valid public places-page response. This is a query smoke, not proof of authenticated create/read persistence. Release evidence records the commit, backend image digest, frontend artifact digest, DSQL migration identifier, telemetry setting, and smoke results. Development seeding is currently disabled until a container-compatible, audited mechanism is implemented; no SSH fallback is allowed.

## Release rollback and recovery

For an application-release failure, stop further promotion and identify the last previously verified development deployment. In **Actions → Roll Back Development Release**, dispatch from `main` with that release's full commit SHA. The workflow requires a successful main-branch release run, a successful development deployment record, and an unexpired release artifact; it reapplies the exact recorded backend image and frontend archive through the existing Terraform state and then runs public health/query checks. If verification fails, keep promotion stopped and record the release digest and failing checks.

For production, use **Deploy Production** with the commit of the previously successful, development-verified release. Its checks require the matching source manifest and deployment evidence; it uses the same backend digest as that dev release. Do not use an arbitrary GHCR tag or rebuild the image for rollback.

These procedures restore application versions only. They do not roll back DSQL schema/data, recover lost database content, or guarantee recovery from infrastructure failure. Keep migrations backward-compatible during promotion; if the failure involves data/schema state or both previous images fail, stop and follow the approved recovery decision/runbook under [Issue #44](https://github.com/alanlima/pawlocal/issues/44). Terraform-managed infrastructure migration rollback requires a separately reviewed state-backed plan and explicit approval; never use manual state edits or out-of-band AWS changes.

## Costs and cleanup

The selected Lightsail Container Service powers are estimated at USD $10/month for development micro and $40/month for production medium (USD $50 total), each at scale one and including the published transfer allowance. The owner authorized this migration after seeing that estimate. It excludes the existing frontend, DSQL usage, backups/audit events, taxes, and transfer overage; monitor actual account costs and recheck before changing service sizes or adding resources.

Remove obsolete AWS resources only through a reviewed Terraform state migration and apply. Do not make out-of-band cleanup changes to resources tracked by the existing state. Keep the shared production frontend and state backend intact.
