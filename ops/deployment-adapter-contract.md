# Full-stack deployment adapter contract

Issue #43 defines the release policy, while the cloud runtime credential path remains under validation. The GitHub workflows therefore call a checked-in environment adapter without selecting how a Lightsail host or another AWS runtime receives deployment and application credentials. Do not add a provider adapter until the owner accepts the runtime identity design and DSQL compatibility/credential checks pass.

## Selection

Each GitHub Actions environment (`development` and `production`) must define the non-secret variables `PAWLOCAL_DEPLOY_ADAPTER_PATH` and `PAWLOCAL_DEPLOY_ROLE_ARN`. The first names an executable, reviewed script under `ops/deployment-adapters/`; the second is a distinct, least-privilege AWS role for that environment. The GitHub OIDC trust must scope its subject to `repo:alanlima/pawlocal:environment:development` or `repo:alanlima/pawlocal:environment:production`, respectively. The wrapper `ops/run-deployment-adapter.sh` rejects missing adapters and paths outside that directory. No adapter or role is configured, so deployment jobs fail closed until they are implemented and selected.

The workflow grants `id-token: write` only to deployment jobs and assumes the environment-specific role with short-lived OIDC credentials. The adapter receives those temporary AWS credentials, the explicitly mapped `PAWLOCAL_PUBLIC_BASE_URL` and `PAWLOCAL_API_HEALTH_URL` values, the deployment manifest and artifacts. No account identifiers, static AWS keys, SSH keys, DSQL runtime credentials, DNS mutation, or host-specific settings are embedded in this interface. If the selected adapter needs a separate deployment secret, add an explicit environment-secret mapping after the identity design is approved; do not assume all GitHub environment secrets are automatically visible to a shell process.

## Commands

The adapter must implement these operations:

```text
<adapter> deploy --environment development|production --manifest <path> --frontend-archive <path>
<adapter> verify --environment development|production --manifest <path> --evidence <path>
```

The adapter receives the matching GitHub Actions environment context and can read that environment's reviewed variables and secrets. `PAWLOCAL_DATABASE_PROVIDER` must be explicitly configured in development; the workflow does not choose a provider. Production passes the provider recorded by the successful development deployment and must reject a mismatch with production's configured provider. It must fail closed if required target configuration or runtime configuration is absent. It must never write application telemetry configuration as enabled; the release manifest and Vite build both set it to `false`.

Release manifest schema is [release-manifest.schema.json](release-manifest.schema.json). It records both provider-specific chains without selecting either: PostgreSQL uses `alembic` with its Alembic revision ID; Aurora DSQL uses `dsql_baseline` with `dsql_0001_initial`. This provider inventory does not approve or configure either database. `deploy` must select `PAWLOCAL_DATABASE_PROVIDER`, verify it has a matching chain entry, and apply only that entry's migration ID. Development chooses its provider from reviewed environment configuration; production must use the same provider and migration ID recorded in the verified development deployment. The same backend digest is used in development and production. The frontend is intentionally built for each environment from the same selected commit because Vite embeds public Cognito settings; it contains no client secret or API credential.

`verify` must perform public frontend and API health checks, verify that the running backend references the manifest's exact image digest, confirm which database provider and migration ID were selected/applied, and write a JSON evidence file at `--evidence`. The evidence must conform to [deployment-evidence.schema.json](deployment-evidence.schema.json), including environment, commit, backend image digest, migration provider/runner/ID, frontend archive digest, telemetry state, public endpoint health results, and verification time. `verify` must exit non-zero if any value differs or any required health check fails. Do not include credentials, tokens, personal information, or database contents in evidence.

## Release evidence and promotion gate

The development workflow creates a GitHub Deployment record only after it has built a non-mock frontend with telemetry disabled and a schema-validated immutable backend image manifest. A deployment status is successful only after evidence has been schema-validated, uploaded, and the adapter verifies the deployed digest and public health checks. The successful development deployment status records the selected database provider and migration runner/ID. The manual production workflow requires:

- a complete commit SHA that is an ancestor of `main`;
- a successful `Full-stack release to development` run for that exact SHA;
- a successful development deployment record tied to that workflow run, with telemetry disabled and a SHA-256 backend digest; and
- the recorded development database provider and migration runner/ID, which production must match; and
- the matching release manifest artifact, whose digest must match the deployment record.

Production deployment concurrency is serialized without canceling an in-progress deployment. Backup, HA, RPO/RTO, restore, recovery, and rollback procedures remain deferred to Issue #44 and are intentionally absent here.

## Required environment configuration before deployment

The development and production GitHub environments need separate values for `PAWLOCAL_DEPLOY_ADAPTER_PATH`, `PAWLOCAL_DEPLOY_ROLE_ARN`, `PAWLOCAL_DATABASE_PROVIDER`, `PAWLOCAL_PUBLIC_BASE_URL`, `PAWLOCAL_API_HEALTH_URL`, `VITE_API_BASE_URL`, and the public `VITE_COGNITO_*` settings. Production `VITE_API_BASE_URL` must be same-origin (`/api/v1`). The adapter must also receive each environment's endpoint and deployment identity configuration from its environment. Runtime database configuration and secret delivery depend on the owner-approved workload identity design; do not fabricate names or credentials before that decision. The current repo has no dedicated GitHub environments, selected adapter, or deployment role, so the deployment jobs are not yet actionable.
