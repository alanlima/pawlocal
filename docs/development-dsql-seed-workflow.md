# Development Aurora DSQL seed workflow

The `Seed development Aurora DSQL` workflow is an on-demand operation for the fixed repository catalog. It runs only from `main`, requires the operator to choose `YES`, and targets the GitHub Environment named `development-seed`. Configure that Environment with a required reviewer and restrict deployments to the `main` branch before running the workflow.

## GitHub Environment configuration

Create `development-seed` in the repository's Environments settings. Set these as Environment **variables**, using the matching development object from Terraform's `environment_targets` output:

| Variable | Terraform output |
|---|---|
| `PAWLOCAL_AWS_ACCOUNT_ID` | `development.aws_account_id` |
| `PAWLOCAL_DSQL_SEED_ROLE_ARN` | `development.dsql_app_iam_principal_arn` |
| `PAWLOCAL_DSQL_ENDPOINT` | `development.dsql_endpoint` |
| `PAWLOCAL_API_HEALTH_URL` | `development.api_health_url` |

These values are configuration, not credentials. Do not add database passwords, access keys, or generated DSQL tokens. The GitHub Environment must exist and be protected before the seed workflow can receive the expected `environment:development-seed` OIDC subject.

The full-stack Terraform root adds that OIDC subject to the existing development DSQL runtime role while preserving the Lightsail service principal trust. The role remains limited to `dsql:DbConnect` on the development cluster; the cluster policy allows the runtime role to connect as `pawlocal_development_app`. This workflow uses that mapped app role, which has `USAGE` and `CREATE` on the `pawlocal` schema and owns the application tables the catalog updates. It has no DSQL admin connection and the workflow cannot target `public` or production.

Terraform code does not enable the workflow in AWS by itself. A separately reviewed Terraform plan and explicitly approved apply must update the development role trust and development cluster policy. Configure and protect the GitHub Environment before the workflow runs. Merging the code alone does not change AWS or execute a seed.

## Run and verify

After the Environment is configured and the Terraform change has been applied through the approved deployment process, open **Actions → Seed development Aurora DSQL**, select the `main` branch, and choose `YES`. The workflow validates the role, AWS account, DSQL endpoint, and HTTPS API URL before obtaining OIDC credentials. It installs the backend runtime package, runs the seed command against `backend/data/seed_places.json`, and checks that DSQL resolves `current_schema()` to `pawlocal` before writing. It then verifies every catalog ID and name through both the development list and detail API routes.

The catalog can update fields in `pawlocal.places` and, when facilities change, rows in `pawlocal.place_facilities`; the runtime app role owns these application tables. No extra table grant is introduced by this workflow. The seed command does not delete rows missing from the catalog, write to `public`, or target production. The run artifact contains the seed outcome and API verification evidence.

Do not use this workflow as a migration or schema-bootstrap path. Schema DDL and production seeding remain separate operations requiring their own authorization.
