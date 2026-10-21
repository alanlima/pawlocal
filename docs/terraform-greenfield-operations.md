# Issue #135 Terraform operations

For the purpose, triggers, inputs, and relationships of every workflow, start with the [GitHub Actions workflow reference](github-actions.md). This guide provides the deeper Terraform state, permission, and operator procedures behind those workflows.

## Status and safety boundary

The configuration, workflows, and validation described here do not prove that bootstrap or application infrastructure was applied. The latest read-only inventory found an empty former application state, no PawLocal application resources, a populated bootstrap state that remains authoritative, and one verified development publisher role eligible for adoption. An unrelated account-level personal workload was verified out of scope and must never be imported, changed, or used as PawLocal evidence.

Only Terraform may change AWS infrastructure or Terraform state. Do not use manual `terraform import`, `terraform state` commands, AWS CLI/SDK mutation, or the AWS console. Local Terraform execution is authorized only for the bootstrap root, after independent review of the exact saved plan. Development and production plans/applies run only through the matching protected GitHub Environments. Billable application resources still require fresh owner cost/provisioning approval.

## Roots and ownership

| Root | Backend key | Owns |
|---|---|---|
| `infra/terraform/iam-bootstrap` | `pawlocal/iam-bootstrap/terraform.tfstate` | Shared GitHub OIDC provider, plan/apply and publisher role objects/trust, baseline permissions, permissions boundaries, runtime identity, private saved-plan transfer bucket |
| `infra/terraform/environments/development` | `pawlocal/development/terraform.tfstate` | Development S3/CloudFront frontend, Route 53 records, Lightsail API, Aurora DSQL, Cognito, environment policies, and matching attachments |
| `infra/terraform/environments/production` | `pawlocal/production/terraform.tfstate` | The same resource types for production only, plus production policies and matching attachments |

The two application roots use `infra/terraform/modules/pawlocal-environment`. The module does not create IAM roles, OIDC providers, trust policies, or permissions boundaries. The former `infra/terraform` and `infra/terraform/fullstack` roots and `pawlocal/terraform.tfstate` key are historical only. The legacy operation and rollback workflows are inert.

The active environment module derives Lightsail resource names from one normalized suffix map and one resource-name object. The API container service keeps the `pawlocal-<environment>-api` name and its certificate uses the distinct `pawlocal-<environment>-api-cert` name. `cert` is the only certificate resource-name suffix; do not introduce `certificate` as an alternate suffix. Bootstrap does not duplicate these application-resource names; their lifecycle remains owned by the matching environment state. Renaming an existing certificate is a replacement operation and may change its DNS validation record, so the protected environment plan must be reviewed before apply.

Previously bootstrap-owned legacy combined-state and identity-stage roles are retained at their existing state addresses to avoid an unrelated identity deletion. Their policies are fail-closed to read-only state/session inspection and contain no application mutation or policy-attachment authority. They are not used by the greenfield workflows.

Plan roles can read AWS resources, read their own state, acquire only their own lock, and upload only their environment plan prefix. Their exact GitHub Environment OIDC subjects are `development-plan` and `production-plan`; both Environments must allow deployments only from `main`. Apply roles can read their approved plan, update only their state, create/update their fixed-name environment policies, and attach them only to the matching bootstrap roles. A bootstrap-owned boundary caps the effective application actions. It excludes role creation, trust changes, boundary changes, cross-environment attachments, and authorization-tag removal.

## Validate locally without AWS access

```powershell
terraform fmt -check -recursive infra/terraform

$roots = @(
  "infra/terraform/iam-bootstrap",
  "infra/terraform/environments/development",
  "infra/terraform/environments/production"
)
foreach ($root in $roots) {
  terraform -chdir=$root init -backend=false -input=false
  terraform -chdir=$root validate -no-color
}

python -m unittest tests.ci.test_terraform_greenfield -v
```

These checks parse configuration only. They are not a state-backed plan, apply, deployment, DSQL compatibility result, or public health check.

## Prepare and review the bootstrap plan

Keep all values in the operator credential provider and process environment. Do not write a populated tfvars file to the repository. The bootstrap state already exists; use its existing backend key and normal refresh.

```powershell
$env:TF_VAR_terraform_state_bucket_name = "<existing state bucket>"
$env:TF_VAR_github_repository = "alanlima/pawlocal"
$env:TF_VAR_github_owner_id = "<immutable owner ID>"
$env:TF_VAR_github_repository_id = "<immutable repository ID>"
$env:TF_VAR_route53_zone_id = "<existing hosted zone ID>"
$env:TF_VAR_domain_name = "<base hosted zone name>"
$env:TF_VAR_manage_github_oidc_provider = "true"
$env:TF_VAR_import_existing_github_oidc_provider = "true"
$env:TF_VAR_import_existing_development_deploy_role = "true"
$env:TF_VAR_import_existing_dsql_service_linked_role = "true"

terraform -chdir=infra/terraform/iam-bootstrap init -input=false -reconfigure `
  -backend-config="bucket=$env:TF_VAR_terraform_state_bucket_name" `
  -backend-config="key=pawlocal/iam-bootstrap/terraform.tfstate" `
  -backend-config="region=ap-southeast-2" `
  -backend-config="encrypt=true" `
  -backend-config="use_lockfile=true"

terraform -chdir=infra/terraform/iam-bootstrap plan -input=false -lock-timeout=5m -out=iam-bootstrap.tfplan
terraform -chdir=infra/terraform/iam-bootstrap show -no-color iam-bootstrap.tfplan
Get-FileHash infra/terraform/iam-bootstrap/iam-bootstrap.tfplan -Algorithm SHA256
```

The independent reviewer must confirm:

- the existing populated bootstrap resources remain under their current addresses unless the change intentionally replaces a prior inline application permission with the new boundary/baseline model;
- exactly three state-backed former bootstrap app-specific managed policies (development frontend, production frontend, and development runtime) are planned for deletion through their declarative `removed` blocks, leaving the environment states as their sole replacements/owners;
- exactly two legacy `environment_service_apply` inline role policies are planned for deletion as the intentional removal of prior inline application authority now replaced by the boundary/environment-owned policy model;
- the defensive `identity_production_runtime` removed address is absent from the populated bootstrap state and therefore produces no fourth deletion or other planned change;
- no other resource is deleted or replaced;
- the only imports are the existing GitHub OIDC provider, the verified development publisher role, and the already-existing fixed DSQL service-linked role selected by the explicit flags;
- no application resource is imported;
- the development publisher role is updated in place, not replaced or deleted;
- the production publisher role and environment boundaries are the expected creates;
- no credential or secret value appears in the plan or review evidence; and
- no unrelated account-level workload appears in the plan.

### Recover the partial bootstrap apply

The first reviewed bootstrap apply completed the approved imports, legacy policy removals, and identity work, but failed before creating the two environment apply boundaries. The bootstrap state serial advanced, so that saved plan is stale and must not be retried even if its file and digest are unchanged.

AWS permits at most 6,144 non-whitespace bytes in a managed-policy document. This root enforces a 6,100-byte repository budget against the actual minified development and production boundary JSON. A synthetic length-equivalent test fixture locks in the reviewed shape without exposing live identifiers. Both environments use the same required policy families and matching frontend-object deletion boundary ceiling, so bootstrap does not depend on a particular environment deployment order. Exact environment ARNs, state keys, role names, and OIDC subjects remain isolated; teardown also remains default-off and protected by its dedicated workflow. The compact boundaries keep mutation ceilings, environment isolation, authorization-tag conditions, and separate CloudFront distribution/OAC statements; compact Cognito and Lightsail action families remain intersected with the exact identity-policy actions. Post-create mutations use compatible DSQL cluster, Cognito user-pool, Lightsail certificate, and Lightsail container-service ARN families instead of a literal wildcard resource. DSQL and Lightsail retain matching authorization-tag conditions; the Cognito client/domain actions use the stable user-pool family because AWS lists that resource type but no action-level condition keys for those mutations.

After merging the size-safe configuration, discard any stale plan and generate a fresh normal-refresh bootstrap plan from merged `main` using the same reviewed inputs. The plan must show the stable boundary changes described in this document and only the dependent bootstrap-owned role, inline-policy, and permissions-boundary changes required by the current state. It must contain zero unapproved imports, deletes, or replacements, and no application or unrelated resources. Because a partial apply can change which bootstrap resources already exist, do not rely on an earlier expected action count. Any unexplained action invalidates this recovery path and requires investigation plus a new independent review. Apply only the newly reviewed exact saved plan; never use the failed apply's plan binary.

Only after that exact plan and digest receive independent approval may the owner-authorized operator run:

```powershell
terraform -chdir=infra/terraform/iam-bootstrap apply -input=false iam-bootstrap.tfplan
```

Changing any input or source invalidates the review: discard the plan, create a fresh saved plan, and repeat review. Never commit or upload the raw plan to GitHub.

## Protected GitHub Environment configuration

Create or update values only after the bootstrap apply outputs are verified. Never store static AWS access keys. Both `development-plan` and `production-plan` need the same variable names, with environment-specific role values:

- `AWS_REGION`
- `PAWLOCAL_AWS_ACCOUNT_ID`
- `PAWLOCAL_TF_STATE_BUCKET`
- `PAWLOCAL_TERRAFORM_PLAN_BUCKET`
- `PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN`
- `PAWLOCAL_DOMAIN_NAME`
- `PAWLOCAL_ROUTE53_ZONE_ID`
- `PAWLOCAL_RUNTIME_ROLE_ARN` (empty for the first foundation stage)
- `PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN` (empty until the first foundation apply returns the exact ARN)
- `PAWLOCAL_CLOUDFRONT_OAC_ARN` (empty until the first foundation apply returns the exact ARN)
- secret `PAWLOCAL_CLOUDFRONT_CERTIFICATE_ARN`

The matching `development-apply` and `production-apply` Environments use the same names plus `PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN`. Restrict them to `main` and require reviewers. Release Environments `development` and `production` use `PAWLOCAL_DEPLOY_ROLE_ARN` for the narrow frontend publisher plus the existing public application configuration used by the deployment adapter. After the foundation apply, set `PAWLOCAL_FRONTEND_BUCKET` and `PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID` from the matching `environment_targets` output; never copy one environment's target into the other.

Do not print Environment or secret values as evidence. Record only which required names are configured and whether protection rules are enabled.

## Environment lifecycle phases

Foundation, Converge, and Release are one environment lifecycle with three explicit phases. Foundation and Converge cannot be one Terraform plan/apply: Foundation must first create the AWS-generated Lightsail principal and CloudFront identifiers that the bootstrap and environment states consume during the handoff. They may eventually be presented as one operator-triggered provisioning workflow, but that workflow would still execute separate reviewed Foundation, bootstrap, and Converge plans/applies. Automated handoff remains deferred under [Issue #155](https://github.com/alanlima/pawlocal/issues/155).

### Why the phases are different

Terraform fixes a saved plan before applying it; it cannot pause that plan, apply a second state, introduce newly generated values, and then resume the original plan. PawLocal also deliberately separates shared IAM bootstrap ownership from each environment's application state. That creates a one-time dependency sequence:

1. Foundation asks AWS to create the environment resources whose identifiers cannot be predicted safely, including the Lightsail service principal and CloudFront distribution/OAC identifiers.
2. The bootstrap state consumes the exact Lightsail principal and creates the matching runtime trust. The protected Environment handoff supplies the generated CloudFront identifiers and resulting runtime-role ARN to the environment root.
3. Converge creates the DSQL runtime mapping and baseline, backend deployment version, API DNS, and exact generated-resource permissions that could not exist during Foundation.
4. After Converge, those infrastructure identities are stable. Release therefore changes only the selected immutable application version, then publishes and verifies the corresponding frontend, instead of repeating infrastructure provisioning.

The split is therefore caused by generated AWS identities and Terraform state ownership, not by a different application artifact or an incident-recovery path.

| Phase | Purpose | Key inputs | Result |
|---|---|---|---|
| **Foundation** | Create the base environment and the AWS-generated identities needed by later IAM configuration. | `phase=foundation`, empty `backend_image`, empty `release_commit`, `release_only=false` | Creates the base S3/CloudFront, DSQL, Cognito, certificate, Lightsail service, and DNS infrastructure. Runtime deployment, DSQL application setup, and API DNS remain disabled. |
| **Converge** | Complete the generated-identity handoff and reach the first fully deployable environment state. | `phase=converge`, exact immutable `backend_image`, `release_only=false`; production also requires its matching development-verified `release_commit` | With complete handoff inputs, applies exact generated-resource permissions, completes DSQL setup, creates the backend deployment version and API DNS, and converges all remaining infrastructure. The current workflow does not enforce that completeness. |
| **Release** | Promote a later application version without using the lifecycle to redesign infrastructure. | `phase=release`, immutable `backend_image`, `release_only=true`. The development full-stack caller supplies its current `main` commit; production requires the matching development-verified commit/image pair. | Declares the container deployment version as the only intended Terraform change; the calling release workflow then publishes the frontend and verifies the public frontend, API, and database-backed journey. |

Current Converge behavior is fail-open with respect to generated handoff readiness. `phase=converge` selects the same plan and apply jobs as the other phases; it does not require `PAWLOCAL_RUNTIME_ROLE_ARN`, `PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN`, or `PAWLOCAL_CLOUDFRONT_OAC_ARN`. When those protected values are absent, Terraform may disable dependent resources and return a successful zero-change or incomplete handoff apply. Until [Issue #176](https://github.com/alanlima/pawlocal/issues/176) changes this behavior, operators must independently compare the matching Foundation outputs and bootstrap runtime identity with the protected plan variables, inspect the exact plan for the expected resources, and verify public and runtime readiness after apply. A green Converge run alone is not readiness evidence.

The first deployment, and a deployment after a complete approved destroy, follows this sequence:

```text
Foundation apply
  -> read the generated CloudFront distribution/OAC and Lightsail principal outputs
  -> apply the matching bootstrap runtime-trust handoff
  -> update the matching protected Environment variables
  -> Converge apply
  -> Release for subsequent verified application versions
```

Do not use `release` for the first deployment. `terraform-environment.yml` owns Foundation and Converge. `deploy-production.yml` supplies `phase=release` for the normal production promotion path after the environment has converged.

Issue #148 keeps automated ownership and release-only rejection disabled with `--skip-enforcement` for the MVP. `release_only=true` still identifies the intended scope, but the protected reviewer must reject an exact Release plan containing any change beyond the container deployment version.

### Protected plan and apply mechanics

Dispatch `Terraform environment plan and apply` from `main`. The workflow:

1. assumes the matching read-only plan role;
2. initializes only `pawlocal/<environment>/terraform.tfstate`;
3. writes the binary plan only in the runner workspace;
4. renders a sanitized summary containing resource types, actions, and counts only;
5. renders the sanitized summary with ownership enforcement explicitly skipped during the first MVP deployment and partial-apply rerun window, as tracked by [Issue #148](https://github.com/alanlima/pawlocal/issues/148);
6. uploads the opaque saved plan plus bound metadata to the private one-day transfer prefix;
7. pauses at the matching protected apply Environment; and
8. verifies the metadata and SHA-256 before applying exactly that downloaded plan.

On the first apply, Terraform creates the environment application policy and attaches it to the matching apply role before starting a 30-second provider-managed IAM propagation barrier. Every independent application-resource creation root depends on that barrier, and downstream resources inherit the dependency. If an apply stops after creating the policy or attachment, its saved plan is stale: inspect the partial state, create and independently review a fresh normal-refresh plan, and apply only that newly approved plan. Never retry or reuse the failed apply's saved plan.

Every plan job prints a value-free saved-plan inventory and publishes a sanitized summary containing resource types, actions, fixed Terraform action reasons, and aggregate counts only. For the first MVP deployment and partial-apply rerun window, the summary command passes `--skip-enforcement` under [Issue #148](https://github.com/alanlima/pawlocal/issues/148). During this accepted temporary risk, the summary remains visible but the workflow does not reject imports, deletes, replacements, bootstrap/IAM ownership, or non-release changes. The workflow fails before plan transfer unless `PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS` is exactly `true`, which makes the raw human-readable rendering of the exact saved plan available for inspection before protected apply approval. Review that complete plan at the protected apply gate; exact-plan digest binding, private plan transfer, and protected apply approval remain mandatory.

Terraform init and apply output otherwise remains captured and withheld by default, and failures retain the existing fixed or sanitized diagnostic message. For time-bounded incident diagnosis, a repository administrator may set the repository Actions variable `PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS` to the exact value `true`. Both environment initializations and the exact saved-plan apply then stream Terraform's raw colorized progress live through a pseudo-terminal while retaining the command's real exit status and a runner-local transcript for failure diagnosis. The plan job also prints Terraform's colorized, raw human-readable rendering of the exact saved plan without passing it through the sanitizer. Terraform retains its own sensitive-value redaction, but raw output in this public repository's Actions logs may expose non-secret infrastructure identifiers, resource addresses, hostnames, backend details, and planned or applied values. Disable or remove the variable immediately after diagnosis. The control changes only output capture and color handling; it does not change infrastructure arguments, permissions, saved-plan binding, review, or approval requirements.

Development must be created, reviewed, and live-verified before production. Before any production Terraform plan, the workflow uses the GitHub API to require that the selected commit is in `main`, that the expected main-branch `fullstack-release.yml` run for that exact commit completed successfully, and that its successful development deployment carries validated schema-versioned health, database-query, migration, telemetry, frontend-digest, and backend-digest evidence from the same run/attempt.

### Generated-identifier and runtime handoff

Bootstrap permissions boundaries must not depend on generated full resource ARNs. Their write ceilings use stable resource-family ARNs or deterministic environment/name prefixes. `Resource = "*"` is used only for AWS create actions that have no resource-level authorization, with request-tag conditions wherever AWS supports them. Exact generated resource ARNs are added only to the narrower environment-owned policies after creation; they do not trigger a bootstrap boundary rewrite.

Terraform AWS provider 6.69.1 submits the standard application tags during S3, DSQL, Lightsail, Cognito, and CloudFront creation. The matching apply identity policy and bootstrap boundary therefore include only the service-specific dependent tag authorizations needed by those create calls. S3 `CreateBucket` and `s3:TagResource` require the exact environment bucket prefix, expected tag keys, and complete tag values, so the provider's untagged retry remains fail-closed. S3 bucket tags are not consistently available to the immediate ownership, encryption, public-access, policy, and cleanup authorization checks, so those bucket-level actions are restricted by the generated matching environment bucket-name prefix rather than resource-tag conditions. The same name boundary permits only the provider refresh reads, `ListBucket`, `ListTagsForResource`, and `PutBucketTagging`; it does not cross environments. DSQL, Cognito user-pool, Lightsail certificate/service, and CloudFront function/distribution create-time tag handoffs require both the complete matching request-tag contract and the matching authorization tags surfaced by the services during dependent `TagResource` evaluation; they no longer require those resource tags to be absent. Generated resource wildcards are used only where the AWS create-time authorization model requires them.

The bootstrap boundary is stable before and after CloudFront creation and does not accept generated distribution or OAC ARN inputs. Distribution update/delete actions use only the account distribution family and require matching `project` and `environment` resource tags. OAC update/delete actions are kept in a separate statement over the account OAC family. CloudFront OAC ARNs contain generated IDs, do not expose a deterministic name/path segment, and do not support a tag condition for these actions, so the boundary alone cannot isolate OACs more narrowly. The environment-owned application policy supplies the exact distribution and OAC ARNs after handoff; effective access is the intersection of that exact policy and the stable boundary.

CloudFront distribution creation still uses the provider's tagged create path and grants no `UntagResource`. After the approved foundation apply, copy the exact distribution and OAC output ARNs into the matching protected Environment variables, then create and review a new environment plan. This tightens the environment-owned identity policy to the exact resources; it does not require another bootstrap boundary plan.

The API deployment and API DNS record remain absent while `PAWLOCAL_RUNTIME_ROLE_ARN` is empty. After the foundation apply, pass the exact Lightsail `principal_arn` output into the matching bootstrap runtime-role input and apply a separately reviewed bootstrap plan. Set the resulting runtime role ARN in the environment variables, then run a new environment plan with the immutable backend image. This generated principal remains a required trust-policy handoff; generated application resource ARNs are no longer bootstrap boundary inputs. This breaks the identity dependency without manual AWS or state mutation.

The existing protected environment apply performs the DSQL catalog setup before it can create or update a Lightsail deployment version. Terraform first attaches an exact environment-owned setup policy to the matching apply role, waits for that policy and the cluster policy to propagate, and then runs one `terraform_data` setup gate. Its state contains only digests of the cluster identity, runtime identity, and reviewed setup revision. An image-only deployment leaves those triggers unchanged and plans the setup gate as a no-op.

The setup gate has two identities and phases. The protected apply role connects as DSQL `admin` only to create and verify the application role, exact singleton runtime IAM mapping, `pawlocal` schema, and narrow `USAGE`/`CREATE` grants. It then assumes only the matching runtime role, connects as the application database role, applies the existing `dsql_0001_initial` clean baseline, and verifies the exact revision, expected tables and owners, and complete async-index definitions and owners. The apply/admin identity is never mapped as the application role and does not own application tables or indexes. A missing, duplicate, or competing mapping, a broad `PUBLIC` schema grant, a wrong table or index owner, or a missing/invalid index fails closed before Lightsail deployment.

If either phase fails, Terraform cannot record the setup gate as successful and the dependent deployment version remains blocked. Generate and independently review a fresh plan; the next protected apply retries the idempotent role and baseline operations. Changing the reviewed setup revision reasserts all postconditions. There is no separate workflow, recovery operator, or local bootstrap script. Seeds, the PostgreSQL Alembic chain, forward DSQL upgrades, and destructive catalog cleanup remain outside this path.

Lightsail update and deployment actions require `project=pawlocal` and the matching `environment` resource tag. The role has no `lightsail:UntagResource`. During tagged creation, AWS evaluates the dependent `lightsail:TagResource` authorization against the pre-creation `ContainerService/*` and `Certificate/*` resource forms, so both the environment identity policy and bootstrap boundary admit only those forms with the matching request and authorization tags. Their intersection keeps post-create mutation environment-scoped and cannot remove the authorization tags.

Lightsail certificate and container-service create/delete operations are asynchronous. The pinned AWS provider polls each exact request with the singular `lightsail:GetOperation`; the plural `lightsail:GetOperations` only lists operations and cannot satisfy that waiter. Both plan and apply roles therefore retain the singular read alongside the service-specific refresh reads. After changing bootstrap permissions, apply an independently reviewed fresh bootstrap plan before generating a fresh environment plan; never reuse the failed saved plan or manually edit/import state.

## Release and verification

`Full-stack release to development` publishes an immutable backend image from `main`, calls the environment workflow with `environment=development` and `release_only=true`, publishes the frontend with the narrow publisher role, runs the deployment adapter's public health/database smoke verification, and records a successful GitHub development deployment only after verification.

`Promote verified release to production` is manual. Supply the full verified commit SHA and exact immutable image reference recorded by development. The environment workflow rejects production before it finds the matching successful development deployment. It plans/applies only the production root, after production approval, then builds the selected commit's production frontend and runs the same public verification.

Passing CI or Terraform apply is not deployment completion. Before closing Issue #135, evidence must separately show the exact saved plans, approvals, successful development verification, production promotion of the same digest, live public health and database-query smoke, and current runtime state. DSQL identity/credential refresh remains a mandatory live gate. Telemetry, backup, HA, restore, rollback, and recovery are not part of Issue #135.
