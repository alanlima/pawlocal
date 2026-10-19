# AWS deployment and full-stack release status

The tracked `infra/terraform/` directory is the sole Terraform root and uses the existing `pawlocal/terraform.tfstate` S3 backend. It retains the existing production frontend bucket, CloudFront distribution, DNS records, and account GitHub OIDC provider in the same state. The `fullstack/` module has no backend of its own. Development and production APIs use separate Lightsail Container Services and Aurora DSQL clusters. Production frontend publishing continues to use the root state's existing S3 bucket and CloudFront distribution.

The owner accepted the Lightsail Container Service design through Issue #75. This implementation replaces the Lightsail VM/static-IP API path with container services, managed endpoint TLS, Route 53 CNAME records, public digest-pinned GHCR images, and Terraform-managed deployment versions. The Lightsail service principal is configured as the DSQL runtime identity. Its database authentication path still needs live validation. Two unused CLI-created DSQL access keys were deleted after CloudTrail and IAM checks. No AWS infrastructure apply was performed as part of this implementation.

## AWS infrastructure ownership rule

Terraform configuration and the existing shared Terraform state are the only mechanism for creating, changing, replacing, or deleting AWS infrastructure. This covers compute and app deployments, databases, identity, DNS, certificates, networking, IAM, storage, and monitoring. AWS console, CLI, SDK, shell, and bootstrap scripts must not mutate infrastructure or Terraform state. Do not manually edit, import, or remove state bindings. CI may build and publish immutable artifacts; any AWS-side application deployment must be represented by a Terraform resource in the shared state. Runtime secrets must not be stored in Terraform state. An infrastructure migration requires a complete reviewed plan and explicit cost/provisioning approval.

The frontend publisher uses AWS CLI only for application artifact operations (`s3 sync`, release archive upload, and CloudFront invalidation). It does not create or configure AWS resources. Backend container deployments use `aws_lightsail_container_service_deployment_version` through the existing Terraform root state.

## Architecture

The frontend remains a private S3 origin behind CloudFront OAC with HTTPS, SPA fallback, and Route 53 alias records. The API is served directly by the Lightsail Container Service public endpoint; Route 53 CNAME records map `api-dev.<domain>` and `api.<domain>` to its generated hostname. Terraform creates domain-validation records, and Lightsail manages the endpoint certificate. Frontend and API origins remain separate.

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

### Issue #75 integrated migration plan review (2026-10-19)

A read-only plan was generated against the existing shared S3 state using the same root configuration, Sydney region, current public DNS zone and CloudFront certificate, and a digest-pinned image from a successful main release. It proposed **14 creates, 16 deletes, 2 replacements, 2 in-place updates, and 2 data reads**. No apply or infrastructure mutation was run. The saved plan and JSON were kept outside the repository and are a snapshot only; regenerate before any later apply.

The 16 deletions are the two Lightsail VMs, public-port configurations, static IPs and attachments, IAM app users and their DSQL policies, and temporary-ingress roles and policies. The 14 creates are the two container services, deployments, Lightsail certificates, certificate-validation DNS records, DSQL cluster policies, and environment-scoped Terraform deployment roles and policies. The two `terraform_data.app_dsql_role` replacements rerun the idempotent database-role mapping helper because its source/configuration trigger changed. The two API DNS updates switch each old A record to its service CNAME; the pinned AWS provider plans this as a record update, which sends a delete-old/create-new change batch for the old and new record types.

The plan did not change the existing production frontend bucket, CloudFront distribution, frontend DNS aliases, state backend, account OIDC provider, DSQL clusters, or Cognito pools/clients. No unrelated infrastructure drift or resource-address replacement appeared. The pinned AWS provider's Route 53 record update path batches deletion of the prior record type and creation of the new type in one change batch ([provider v6.69.1 source](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/internal/service/route53/record.go#L3399-L3422)). These observations review the migration shape, but do not authorize applying it or establish live DSQL credentials, connection refresh, or runtime compatibility. The proposed container sizes also exceed the previously approved VM cost estimate; obtain explicit cost/provisioning approval before applying.

## GitHub release configuration

Development and production environments provide `AWS_REGION`, `PAWLOCAL_DEPLOY_ROLE_ARN`, `PAWLOCAL_TERRAFORM_ROLE_ARN`, `PAWLOCAL_TF_STATE_BUCKET`, `PAWLOCAL_DOMAIN_NAME`, `PAWLOCAL_CERTIFICATE_ARN`, frontend bucket/distribution IDs, API health/public URLs, DSQL nonsecret configuration, and public Cognito settings. The Terraform role needs access to the existing state and the reads/actions required to plan and deploy only the environment's Lightsail container deployment. The frontend role is limited to publishing frontend artifacts and invalidating its distribution. Do not configure SSH private keys or DSQL access-key secrets for these workflows.

The release script uses the Terraform state output as the source of the other environment's image digest. It plans with the target environment's release manifest, validates that the plan changes only that environment's `aws_lightsail_container_service_deployment_version` and contains the exact selected digest, then applies that exact saved plan. A pending infrastructure migration or any unrelated drift causes the release to fail closed; review and resolve it separately.

Public verification checks the frontend HTML, API health endpoint, and a valid public places-page response. This is a query smoke, not proof of authenticated create/read persistence. Release evidence records the commit, backend image digest, frontend artifact digest, DSQL migration identifier, telemetry setting, and smoke results. Development seeding is currently disabled until a container-compatible, audited mechanism is implemented; no SSH fallback is allowed.

## Release rollback and recovery

For an application-release failure, stop further promotion and identify the last previously verified development deployment. In **Actions → Roll Back Development Release**, dispatch from `main` with that release's full commit SHA. The workflow requires a successful main-branch release run, a successful development deployment record, and an unexpired release artifact; it reapplies the exact recorded backend image and frontend archive through the existing Terraform state and then runs public health/query checks. If verification fails, keep promotion stopped and record the release digest and failing checks.

For production, use **Deploy Production** with the commit of the previously successful, development-verified release. Its checks require the matching source manifest and deployment evidence; it uses the same backend digest as that dev release. Do not use an arbitrary GHCR tag or rebuild the image for rollback.

These procedures restore application versions only. They do not roll back DSQL schema/data, recover lost database content, or guarantee recovery from infrastructure failure. Keep migrations backward-compatible during promotion; if the failure involves data/schema state or both previous images fail, stop and follow the approved recovery decision/runbook under [Issue #44](https://github.com/alanlima/pawlocal/issues/44). Terraform-managed infrastructure migration rollback requires a separately reviewed state-backed plan and explicit approval; never use manual state edits or out-of-band AWS changes.

## Costs and cleanup

The selected Lightsail Container Service powers are currently estimated at USD $10/month for development micro and $40/month for production medium (USD $50 total), each at scale one and including the published transfer allowance. The estimate excludes the existing frontend, DSQL usage, backups/audit events, taxes, and transfer overage. Recheck current AWS prices and the complete account-level estimate before applying infrastructure changes. This container estimate is not a cost approval.

Remove obsolete AWS resources only through a reviewed Terraform state migration and apply. Do not make out-of-band cleanup changes to resources tracked by the existing state. Keep the shared production frontend and state backend intact.
