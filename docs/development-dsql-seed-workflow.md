# Development Aurora DSQL seed workflow

The `Seed development Aurora DSQL` workflow is an on-demand operation for the fixed repository catalog. It runs only from `main` and targets the GitHub Environment named `development-seed`. Configure that Environment with a required reviewer and restrict deployments to the `main` branch before running the workflow. The protected Environment approval is the human confirmation gate; the dispatch form does not add a second confirmation checkbox.

## GitHub Environment configuration

The protected `development-seed` Environment stores these four values as Environment **secrets**, using the matching development object from Terraform's `environment_targets` output:

| Environment secret | Terraform output |
|---|---|
| `PAWLOCAL_AWS_ACCOUNT_ID` | `development.aws_account_id` |
| `PAWLOCAL_DSQL_SEED_ROLE_ARN` | `development.dsql_app_iam_principal_arn` |
| `PAWLOCAL_DSQL_ENDPOINT` | `development.dsql_endpoint` |
| `PAWLOCAL_API_HEALTH_URL` | `development.api_health_url` |

The endpoint was first moved to an Environment secret in PR #164; the account, role, and API URL were subsequently moved to secrets as well. No same-named Environment variables remain. These values are configuration, not credentials, but the live identifiers must be masked in public Actions logs. Do not add database passwords, access keys, or generated DSQL tokens. The workflow derives the database URL only in the seed step, masks it before use, and keeps the account, role, endpoint, and API URL out of uploaded evidence. The GitHub Environment must remain protected with one required reviewer and a `main`-only branch policy so the seed workflow receives the expected `environment:development-seed` OIDC subject. When rotating a value, update its Environment secret and do not recreate an ordinary variable or copy the value into an issue, PR, command line, or artifact. GitHub masks secret values in logs, but transformed values require their own masking or sanitized output; review the resulting log and artifacts for identifiers before citing them as evidence.

The full-stack Terraform root adds that OIDC subject to the existing development DSQL runtime role while preserving the Lightsail service principal trust. The role remains limited to identity-based `dsql:DbConnect` on the development cluster; the cluster policy delegates `dsql:DbConnectAdmin` to account identities. The app-specific cluster-policy `dsql:DbConnect` statement is proposed for removal. The seed workflow uses the mapped `pawlocal_development_app` role, which has `USAGE` and `CREATE` on the `pawlocal` schema and owns the application tables the catalog updates. It has no DSQL admin connection and the workflow cannot target `public` or production. The successful seed run used the app-specific grant and does not prove connectivity after its removal; rerun the seed and verify the API after the Terraform policy change is applied.

Terraform code does not enable the workflow in AWS by itself. A separately reviewed Terraform plan and explicitly approved apply must update the development role trust and cluster policy. The existing environment-scoped Terraform release role is deliberately limited to state operations, refresh reads, and creating its selected Lightsail deployment; it cannot update DSQL cluster policies. Do not expand that role as part of an app release. The current workflow has no separate privileged Terraform apply path, so the policy change cannot be applied through the existing deployment job. Configure and protect the GitHub Environment before the seed workflow runs. Merging the code alone does not change AWS or execute a seed.

## Run and verify

After the Environment is configured and the Terraform change has been applied through the approved deployment process, open **Actions → Seed development Aurora DSQL**, select the `main` branch, and run the workflow. Approve the protected `development-seed` Environment when prompted. The workflow validates the role, AWS account, DSQL endpoint, and HTTPS API URL before obtaining OIDC credentials. It installs the backend runtime package, runs the seed command against `backend/data/seed_places.json`, and checks that DSQL resolves `current_schema()` to `pawlocal` before writing. It then verifies every catalog ID and name through both the development list and detail API routes.

The catalog can update fields in `pawlocal.places` and, when facilities change, rows in `pawlocal.place_facilities`; the runtime app role owns these application tables. No extra table grant is introduced by this workflow. The seed command does not delete rows missing from the catalog, write to `public`, or target production. The run artifact contains the seed outcome and API verification evidence.

Do not use this workflow as a migration or schema-bootstrap path. Schema DDL and production seeding remain separate operations requiring their own authorization.
