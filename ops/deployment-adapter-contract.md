# Full-stack deployment adapter contract

Issue #43 defines the release policy. The owner selected Lightsail + Aurora DSQL and one long-term IAM access key per environment for application authentication. The Issue #62 adapter is being implemented; DSQL runtime compatibility and live validation remain incomplete. No credentials or resources have been created.

## Selection

Each GitHub Actions environment (`development` and `production`) must define the non-secret variables `PAWLOCAL_DEPLOY_ADAPTER_PATH` and `PAWLOCAL_DEPLOY_ROLE_ARN`. The first names an executable, reviewed script under `ops/deployment-adapters/`; the second is a distinct, least-privilege AWS role for that environment. The GitHub OIDC trust must scope its subject to `repo:alanlima/pawlocal:environment:development` or `repo:alanlima/pawlocal:environment:production`, respectively. The wrapper `ops/run-deployment-adapter.sh` rejects missing adapters and paths outside that directory. No adapter or role is configured, so deployment jobs fail closed until they are implemented and selected.

The workflow grants `id-token: write` only to deployment jobs and assumes an environment-specific deployment role with short-lived OIDC credentials. The adapter separately receives explicitly mapped SSH private key/known-host values and the environment's DSQL IAM access key via GitHub environment secrets. It sends the app key only over SSH stdin to a root-owned installer, which writes a mode-0600 shared credentials file. The key is excluded from command arguments, logs, Terraform, user data, images, and artifacts. The app uses the AWS SDK default credential chain; the deployment OIDC identity is not reused as app identity.

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

Each environment needs `PAWLOCAL_DEPLOY_ADAPTER_PATH`, `PAWLOCAL_DEPLOY_ROLE_ARN`, `PAWLOCAL_DATABASE_PROVIDER=aurora_dsql`, public/API URLs, DSQL endpoint and database role, SSH target/known-host settings, and public Vite Cognito configuration. Secrets are `PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY`, `PAWLOCAL_DSQL_ACCESS_KEY_ID`, and `PAWLOCAL_DSQL_SECRET_ACCESS_KEY`, independently scoped per environment. Production `VITE_API_BASE_URL` must be same-origin (`/api/v1`). Terraform and GitHub environment configuration are not yet reviewed or deployed; DSQL live validation is incomplete, so jobs are not yet actionable.
