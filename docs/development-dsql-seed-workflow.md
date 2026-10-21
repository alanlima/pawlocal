# Development Aurora DSQL seed workflow

The `Seed development Aurora DSQL` workflow is an on-demand operation for the fixed repository catalog. It runs only from `main` and targets the GitHub Environment named `development-seed`. Configure that Environment with a required reviewer and restrict deployments to the `main` branch before running the workflow. The protected Environment approval is the human confirmation gate; the dispatch form does not add a second confirmation checkbox.

## GitHub Environment configuration

Create `development-seed` in the repository's Environments settings. Set each value from the matching development object in Terraform's `environment_targets` output:

| Setting | GitHub Environment type | Terraform output |
|---|---|---|
| `PAWLOCAL_AWS_ACCOUNT_ID` | Variable | `development.aws_account_id` |
| `PAWLOCAL_DSQL_SEED_ROLE_ARN` | Variable | `development.dsql_app_iam_principal_arn` |
| `PAWLOCAL_DSQL_ENDPOINT` | Secret | `development.dsql_endpoint` |
| `PAWLOCAL_API_HEALTH_URL` | Variable | `development.api_health_url` |

The endpoint is not an authentication credential, but it is stored as a GitHub Environment secret so Actions masks the endpoint and the derived database URL in public run logs. Do not also define `PAWLOCAL_DSQL_ENDPOINT` as an Environment variable; the secret is the single source of truth. The other settings remain Environment variables. Do not add database passwords, access keys, or generated DSQL tokens. The GitHub Environment must exist and be protected before the seed workflow can receive the expected `environment:development-seed` OIDC subject.

The full-stack Terraform root adds that OIDC subject to the existing development DSQL runtime role while preserving the Lightsail service principal trust. The role remains limited to identity-based `dsql:DbConnect` on the development cluster; the cluster policy delegates `dsql:DbConnectAdmin` to account identities. The app-specific cluster-policy `dsql:DbConnect` statement is proposed for removal. The seed workflow uses the mapped `pawlocal_development_app` role, which has `USAGE` and `CREATE` on the `pawlocal` schema and owns the application tables the catalog updates. It has no DSQL admin connection and the workflow cannot target `public` or production. The successful seed run used the app-specific grant and does not prove connectivity after its removal; rerun the seed and verify the API after the Terraform policy change is applied.

Terraform code does not enable the workflow in AWS by itself. A separately reviewed Terraform plan and explicitly approved apply must update the development role trust and cluster policy. The existing environment-scoped Terraform release role is deliberately limited to state operations, refresh reads, and creating its selected Lightsail deployment; it cannot update DSQL cluster policies. Do not expand that role as part of an app release. The current workflow has no separate privileged Terraform apply path, so the policy change cannot be applied through the existing deployment job. Configure and protect the GitHub Environment before the seed workflow runs. Merging the code alone does not change AWS or execute a seed.

## Run and verify

After the Environment is configured and the Terraform change has been applied through the approved deployment process, open **Actions → Seed development Aurora DSQL**, select the `main` branch, and run the workflow. Approve the protected `development-seed` Environment when prompted. The workflow validates the role, AWS account, DSQL endpoint, and HTTPS API URL before obtaining OIDC credentials. It installs the backend runtime package, runs the seed command against `backend/data/seed_places.json`, and checks that DSQL resolves `current_schema()` to `pawlocal` before writing. It then verifies every catalog ID and name through both the development list and detail API routes.

The catalog can update fields in `pawlocal.places` and, when facilities change, rows in `pawlocal.place_facilities`; the runtime app role owns these application tables. No extra table grant is introduced by this workflow. The seed command does not delete rows missing from the catalog, write to `public`, or target production. The run artifact contains the seed outcome and API verification evidence.

Do not use this workflow as a migration or schema-bootstrap path. Schema DDL and production seeding remain separate operations requiring their own authorization.
