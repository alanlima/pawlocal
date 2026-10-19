# Full-stack deployment adapter contract

The adapter publishes environment-specific frontend artifacts to the Terraform-created private S3 buckets and invalidates the matching CloudFront distribution. It performs public endpoint smoke checks and writes release evidence. It does not deploy backend containers; Terraform owns that deployment through `aws_lightsail_container_service_deployment_version` in the existing shared root state.

## Commands

```text
<adapter> deploy --environment development|production --manifest <path> --frontend-archive <path>
<adapter> verify --environment development|production --manifest <path> --evidence <path>
```

The frontend publisher may use AWS CLI for artifact upload and cache invalidation only. It must not create, modify, or delete AWS infrastructure. Backend release uses `ops/terraform-lightsail-container-deploy.sh`: after the Issue #81 state migration is completed and `PAWLOCAL_TERRAFORM_LAYOUT=split` is set, it loads the other environment's image digest from `pawlocal/app-infra.tfstate`, builds a saved plan, validates that only the selected environment's deployment-version resource changes to the requested immutable image, and applies only that plan. Until the reviewed migration is complete, the script refuses to plan or apply. Any unrelated plan change fails closed.

GitHub Actions assumes environment-specific OIDC roles created and output by Terraform. The Terraform deployment role can read the shared state, refresh infrastructure metadata, and create a deployment only for its matching Lightsail container service. Infrastructure changes require a separate reviewed state-backed plan and explicit cost/provisioning approval. No SSH access or long-lived DSQL access keys are part of the container release path.

`verify` checks public frontend HTML, API health, and a public places-page database query and writes evidence matching [deployment-evidence.schema.json](deployment-evidence.schema.json). The query smoke does not prove authenticated create/read persistence. The DSQL service-principal authentication path and authenticated persistence journey require live validation before production promotion. Development seeding remains disabled until a container-compatible, audited mechanism is implemented.

The release manifest records the immutable backend digest, frontend digest, migration chains, and telemetry state. Development deploys after successful main CI. Production remains a separate manual promotion that selects a verified development release and reuses the same backend image digest. Telemetry stays disabled. Backup, HA, RPO/RTO, restore, recovery, and rollback work remain deferred to Issue #44.
