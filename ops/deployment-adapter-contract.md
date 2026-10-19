# Full-stack deployment adapter contract

Issue #43 defines the release policy. The owner confirmed Lightsail + Aurora DSQL with an access-key runtime and authorized one-off AWS CLI key creation after Terraform creates each app IAM user. Key values stay outside Terraform and are delivered from GitHub environment secrets to a root-owned runtime credentials file over SSH stdin. DSQL runtime compatibility and live validation remain incomplete; the adapter and database-role provisioning changes are not yet deployed.

## Selection

Each GitHub Actions environment (`development` and `production`) must define the non-secret variables `PAWLOCAL_DEPLOY_ADAPTER_PATH` and `PAWLOCAL_DEPLOY_ROLE_ARN`. The first names an executable, reviewed script under `ops/deployment-adapters/`; the second is a distinct, least-privilege AWS role for that environment. The GitHub OIDC trust must scope its subject to `repo:alanlima/pawlocal:environment:development` or `repo:alanlima/pawlocal:environment:production`, respectively. The wrapper `ops/run-deployment-adapter.sh` rejects missing adapters and paths outside that directory. No adapter or role is configured, so deployment jobs fail closed until they are implemented and selected.

The workflow uses short-lived OIDC credentials for AWS publishing. The owner has now authorized one-off AWS CLI creation of access keys after Terraform creates the app IAM principals, and the active release objective requires deploying both environments. The adapter may pass environment-scoped DSQL key values to Lightsail over SSH stdin and keep them in a root-owned, mode-0600 runtime credentials file. Credential values must not appear in Terraform inputs, outputs, state, plans, logs, command arguments, or artifacts.

## Commands

The adapter must implement these operations:

```text
<adapter> deploy --environment development|production --manifest <path> --frontend-archive <path>
<adapter> verify --environment development|production --manifest <path> --evidence <path>
```

The adapter receives the matching GitHub Actions environment context and can read that environment's reviewed variables and secrets. Aurora DSQL is the approved provider for both environments, so the workflows set `PAWLOCAL_DATABASE_PROVIDER=aurora_dsql`; production still rejects any mismatch with the provider recorded by the verified development release. It must fail closed if required target configuration or runtime configuration is absent. It must never write application telemetry configuration as enabled; the release manifest and Vite build both set it to `false`.

Release manifest schema is [release-manifest.schema.json](release-manifest.schema.json). It records both provider-specific chains: PostgreSQL uses `alembic` with its Alembic revision ID; Aurora DSQL uses `dsql_baseline` with `dsql_0001_initial`. Aurora DSQL is approved for this release. The workflow sets `PAWLOCAL_DATABASE_PROVIDER=aurora_dsql`, verifies the matching chain, and applies only that entry's migration ID. Production must use the same provider and migration ID recorded in the verified development deployment. The same backend digest is used in development and production. The frontend is intentionally built for each environment from the same selected commit because Vite embeds public Cognito settings; it contains no client secret or API credential.

`verify` must perform public frontend and API health checks plus a public `GET /api/v1/places` database-query smoke that validates the place-page response shape, verify that the running backend references the manifest's exact image digest, confirm which database provider and migration ID were selected/applied, and write a JSON evidence file at `--evidence`. The application mounts its API router at the configured `/api/v1` prefix; the smoke URL is derived from the Terraform-provided `/health` URL and targets this public route. The evidence must conform to [deployment-evidence.schema.json](deployment-evidence.schema.json), including environment, commit, backend image digest, migration provider/runner/ID, frontend archive digest, telemetry state, public endpoint health results, database-query smoke result, and verification time. This read-only query proves that the public route can execute its repository query path; it does not prove create/read persistence. The authenticated create-then-read persistence journey remains a separate live-development gate until a Cognito test identity is available. `verify` must exit non-zero if any value differs or any required check fails. Do not include credentials, tokens, personal information, or database contents in evidence.

## Release evidence and promotion gate

The development workflow creates a GitHub Deployment record only after it has built a non-mock frontend with telemetry disabled and a schema-validated immutable backend image manifest. A deployment status is successful only after evidence has been schema-validated, uploaded, and the adapter verifies the deployed digest and public health checks. The successful development deployment status records the selected database provider and migration runner/ID. The manual production workflow requires:

- a complete commit SHA that is an ancestor of `main`;
- a successful `Full-stack release to development` run for that exact SHA;
- a successful development deployment record tied to that workflow run, with telemetry disabled and a SHA-256 backend digest; and
- the recorded development database provider and migration runner/ID, which production must match; and
- the matching release manifest artifact, whose digest must match the deployment record.

Production deployment concurrency is serialized without canceling an in-progress deployment. Backup, HA, RPO/RTO, restore, recovery, and rollback procedures remain deferred to Issue #44 and are intentionally absent here.

## Required environment configuration before deployment

Each environment needs `PAWLOCAL_DEPLOY_ADAPTER_PATH`, `PAWLOCAL_DEPLOY_ROLE_ARN`, public/API URLs, DSQL endpoint and database role, SSH target/known-host settings, and public Vite Cognito configuration. Runtime DSQL keys must be supplied only through the matching GitHub Actions environment secrets and installed on Lightsail without passing through Terraform, plans, artifacts, command arguments, or logs. Key issuance is authorized as a one-off AWS CLI operation after Terraform creates the app IAM principal. Production and development `VITE_API_BASE_URL` values must be absolute HTTPS URLs on their matching `api.<domain>` and `api-dev.<domain>` hostnames ending in `/api/v1`. Terraform and GitHub environment configuration are not yet reviewed or deployed; DSQL live validation is incomplete, so jobs are not yet actionable.
