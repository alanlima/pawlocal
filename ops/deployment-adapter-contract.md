# Historical full-stack deployment adapter contract (non-actionable)

> **Do not implement or invoke this contract for Issue #135.** It depends on the superseded combined-state `environment_targets` output and deployment-version address. Retain it only as evidence of the former release path. Issue #135 must define and review a replacement contract after the new development and production state outputs exist; do not infer its paths, outputs, variables, or commands from this file.

Historically, the adapter published environment-specific frontend artifacts to the private S3 bucket and CloudFront distribution returned by the selected environment's `environment_targets` Terraform output from the former shared root state. The remaining details record that retired behavior and are not current requirements.

## Historical commands

```text
<adapter> deploy --environment development|production --manifest <path> --frontend-archive <path>
<adapter> verify --environment development|production --manifest <path> --evidence <path>
```

The frontend publisher may use AWS CLI for artifact upload (`s3 sync`, `s3 cp`) and cache invalidation (`cloudfront create-invalidation`) only. Read-only inspection such as `lightsail get-container-services` is permitted. Shell, Python, and workflow automation must not use AWS CLI or SDKs to create, modify, or delete AWS infrastructure, or mutate Terraform state. CI checks enforce the CLI allowlist, prohibit AWS SDK use in deployment scripts, and reject manual Terraform state commands. Backend release uses `.github/workflows/terraform-environment.yml`: it selects the matching environment root/state, produces a sanitized review summary, transfers an opaque saved plan, and applies only that digest-bound plan after protected approval. `ops/terraform-lightsail-container-deploy.sh` is an inert compatibility stub so historical callers fail closed instead of touching the former combined state.

GitHub Actions assumes environment-specific OIDC roles created and output by bootstrap Terraform. The read-only plan role refreshes only the matching environment root/state; the separately protected apply role can apply the exact reviewed saved plan only within its bootstrap-owned environment boundary. A release-only plan may change only the matching immutable Lightsail deployment-version resource. Foundation changes still require explicit cost/provisioning approval. No SSH access or long-lived DSQL access keys are part of the container release path.

`verify` checks public frontend HTML, API health, and a public places-page database query and writes evidence matching [deployment-evidence.schema.json](deployment-evidence.schema.json). The query smoke does not prove authenticated create/read persistence. The DSQL service-principal authentication path and authenticated persistence journey require live validation before production promotion. Development seeding remains disabled until a container-compatible, audited mechanism is implemented.

The release manifest records the immutable backend digest, frontend digest, migration chains, and telemetry state. Development deploys after successful main CI. Production remains a separate manual promotion that selects a verified development release and reuses the same backend image digest. Telemetry stays disabled. Backup, HA, RPO/RTO, restore, recovery, and rollback work remain deferred to Issue #44.
