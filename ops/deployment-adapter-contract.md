# Full-stack deployment adapter contract

The adapter publishes environment-specific frontend artifacts to the private S3 bucket and CloudFront distribution returned by the selected environment's `environment_targets` Terraform output from the existing shared root state. The workflow must not supply or override these resource identifiers through GitHub variables. It performs public endpoint smoke checks and writes release evidence. It does not deploy backend containers; Terraform owns that deployment through `aws_lightsail_container_service_deployment_version` in the existing shared root state.

## Commands

```text
<adapter> deploy --environment development|production --manifest <path> --frontend-archive <path>
<adapter> verify --environment development|production --manifest <path> --evidence <path>
```

The frontend publisher may use AWS CLI for artifact upload (`s3 sync`, `s3 cp`) and cache invalidation (`cloudfront create-invalidation`) only. Read-only inspection such as `lightsail get-container-services` is permitted. Shell, Python, and workflow automation must not use AWS CLI or SDKs to create, modify, or delete AWS infrastructure, or mutate Terraform state. CI checks enforce the CLI allowlist, prohibit AWS SDK use in deployment scripts, and reject manual Terraform state commands. Backend release uses `ops/terraform-lightsail-container-deploy.sh`: it reads deployment and frontend targets from Terraform outputs, builds a saved plan against the existing S3 backend, validates that only the selected environment's deployment-version resource changes to the requested immutable image, and applies only that plan. Any unrelated plan change fails closed.

GitHub Actions assumes environment-specific OIDC roles created and output by Terraform. The Terraform deployment role can read the shared state, refresh infrastructure metadata, and create a deployment only for its matching Lightsail container service. Infrastructure changes require a separate reviewed state-backed plan and explicit cost/provisioning approval. No SSH access or long-lived DSQL access keys are part of the container release path.

`verify` checks public frontend HTML, API health, and a public places-page database query and writes evidence matching [deployment-evidence.schema.json](deployment-evidence.schema.json). The query smoke does not prove authenticated create/read persistence. The DSQL service-principal authentication path and authenticated persistence journey require live validation before production promotion. Development seeding remains disabled until a container-compatible, audited mechanism is implemented.

The release manifest records the immutable backend digest, frontend digest, migration chains, and telemetry state. Development deploys after successful main CI. Production remains a separate manual promotion that selects a verified development release and reuses the same backend image digest. Telemetry stays disabled. Backup, HA, RPO/RTO, restore, recovery, and rollback work remain deferred to Issue #44.
