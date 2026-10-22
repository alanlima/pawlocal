# Configuration management

This is the implementation contract for [#203](https://github.com/alanlima/pawlocal/issues/203), delivered sequentially through #204 (specification), #205 (callable foundation), and #206 (Terraform/pipeline integration). This document establishes the design, not live deployment or credential setup. Until each implementation is accepted, existing workflows and their manual handoffs remain authoritative.

## Naming and ownership

Use `/pawlocal/<scope>/<classification>/<component>/<setting>`: exactly five nonempty segments after the leading slash. Scope is `development`, `production`, or `shared` only for genuinely shared consumers. Classification is `config` for Parameter Store `String` and `secrets` for `SecureString`. Component and setting are lowercase kebab-case; do not embed account/resource IDs or release versions in names. No shared source is currently required.

The [inventory](configuration-inventory.md) records destinations, validations, consumer and lifecycle ownership. Bootstrap owns generated IAM/account/plan-bucket Strings; each application state owns its generated application Strings. Read-only inventory of existing parameters and Terraform ownership precedes rollout. An unknown existing key or duplicate owner blocks that environment; do not overwrite, import or adopt it. No runtime secret enters Terraform resources, data sources, state or outputs.

## Mapping contract

`ops/configuration/parameter-mapping.yaml` is introduced by #205, with one destination per entry:

```yaml
mappings:
  - store_key: /pawlocal/{environment}/config/auth/client-id
    environment: [development, production]
    github_environment: "{environment}"
    env_name: VITE_COGNITO_CLIENT_ID
    secret: false
    validations: [required]
```

Only these six fields are allowed. `secret` defaults to false and `validations` to an empty list. `environment` selects supported development/production values; substitution accepts only the literal `{environment}` token after validating that input. Targets are exactly the matching release, plan or apply Environment (`{environment}`, `{environment}-plan`, `{environment}-apply`). Expand repeated targets into separate entries. Reject arbitrary target names, cross-environment sources, unknown fields/placeholders, duplicate target/name pairs, inconsistent classification/type/secret flags, and unknown validation rules. Never discover arbitrary keys to synchronize. Required is the initial declared validation; canonical format checks below also apply to their identified values. Lifecycle selection and ownership belong in orchestration/inventory, not extra YAML fields.

## Initial access and GitHub authentication

Before AWS access, configure `AWS_REGION` and `PAWLOCAL_CONFIG_READER_ROLE_ARN` in each matching protected apply Environment from the independently reviewed bootstrap role output. Also establish/read back the initial reader ARN in each matching release Environment (`development` or `production`) as required by #205. The reader role trusts only the exact repository-ID-qualified matching apply Environment OIDC subject, and has bounded reads of selected matching-environment parameters, no writes, no state access, and no cross-environment access. No current mapping uses SecureString, so no decryption grant is needed. Add decryption only for a reviewed real secret consumer and its exact required key/context.

Use one reconciliation mutation job bound to the matching protected apply Environment (`development-apply` or `production-apply`), so its approval, GitHub credential and OIDC reader trust share one job boundary. Approval is required even for audit: audit synchronizes available values. Do not pass secrets through job outputs or assume the development release Environment is protected. Preserve production release/promotion protection as well. For the #205 open-PR feature-branch test, use an opt-in development-only call from the already registered CI-only `ci.yml` manual entry point to the local reusable workflow on that exact branch. Temporarily allowlist only the reviewed branch in `development-apply`, retain its reviewer protection, and remove the allowance after merge. Existing deployment workflows remain unchanged. After merge, verify the new workflow's direct dispatch as well; never broadly permit untrusted PRs.

Ordinary `GITHUB_TOKEN` is not the configuration-write credential. The required setup is an owner-provided, repository-selected fine-grained token stored as `PAWLOCAL_CONFIG_GITHUB_TOKEN` in the matching protected apply Environment, read internally by that job. Limit it to `alanlima/pawlocal` with Environments write and implicit Metadata read; #205 verifies the actual variable and environment-secret API permission requirements. Do not print tokens, expose them as command arguments or outputs, persist temporary tokens, or copy a broad operator OAuth credential into Actions. On 2026-10-22 the owner provisioned this scoped credential in both protected apply Environments and a read-only Environment-variable API check succeeded. Reconciliation writes, reader roles and release readiness remain unverified until #205/#206. No GitHub App identity or speculative App credential parameter is required by this contract.

Initial reader-role publication is a deliberate operator handoff: independently review and apply the bootstrap plan, read actual output ARNs privately, update/read back each matching GitHub variable, then test OIDC. It does not depend on successful reconciliation. Automatic future publication of reader-role ARNs after bootstrap belongs to #191. Region, protected reader-role access, and the GitHub credential must already exist before reconciliation; the reconciler cannot establish its own entry credentials.

### Fresh-operator setup

1. Complete the repository's [Terraform setup and approval procedure](terraform-greenfield-operations.md), including reviewed bootstrap configuration and existing backend/region inputs. #205 must first implement and independently review the reader roles and their non-secret `configuration_reader_role_arns` bootstrap output. Do not attempt reconciliation before those roles are applied.
2. In GitHub, open **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**. Choose resource owner `alanlima`, repository access **Only select repositories → pawlocal**, a bounded expiration, and repository permission **Environments: Read and write**; Metadata read is automatic. No organization, contents-write or unrelated repository permission is needed. Record the expiration in the operator's credential manager so rotation precedes expiry. Follow GitHub's [fine-grained token instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
3. In repository **Settings → Environments → development-apply → Environment secrets**, add `PAWLOCAL_CONFIG_GITHUB_TOKEN`. Repeat in `production-apply` with the approved scoped credential. The **Settings → Secrets and variables → Agents** page configures a separate agent credential domain and does not supply these GitHub Actions Environment secrets. Alternatively use the interactive commands below, entering the token only into the hidden prompt/stdin, never a command argument, chat, checked-in file or shell transcript:

   ```powershell
   gh secret set PAWLOCAL_CONFIG_GITHUB_TOKEN --repo alanlima/pawlocal --env development-apply
   gh secret set PAWLOCAL_CONFIG_GITHUB_TOKEN --repo alanlima/pawlocal --env production-apply
   gh api repos/alanlima/pawlocal/environments/development-apply/secrets --jq '.secrets[].name'
   gh api repos/alanlima/pawlocal/environments/production-apply/secrets --jq '.secrets[].name'
   ```

   Verify names only; GitHub never returns the credential plaintext. Preserve each Environment's required reviewer and branch policies. The supplied credential must be tested against actual variable/secret endpoints in #205; successful secret storage alone is not runtime verification.
4. After independent exact-plan review and authorized bootstrap apply, read the actual role output from the initialized bootstrap root. The commands below describe the #205 output contract; it is not present in the #204 documentation-only baseline. Run from repository root in PowerShell using an independently authorized operator GitHub session for setup. This writes only non-secret entry variables and reads each back, without copying role names from guesses:

   ```powershell
   $readerRoles = terraform -chdir=infra/terraform/iam-bootstrap output -json configuration_reader_role_arns | ConvertFrom-Json
   foreach ($targetEnvironment in @('development', 'production')) {
     $readerArn = $readerRoles.$targetEnvironment
     if (-not $readerArn) { throw 'Missing reviewed reader-role output; stop setup.' }
     foreach ($githubEnvironment in @($targetEnvironment, "$targetEnvironment-apply")) {
       $variableEndpoint = "repos/alanlima/pawlocal/environments/$githubEnvironment/variables"
       $existingVariable = gh api "$variableEndpoint/PAWLOCAL_CONFIG_READER_ROLE_ARN" 2>$null
       if ($LASTEXITCODE -eq 0) {
         gh api --method PATCH "$variableEndpoint/PAWLOCAL_CONFIG_READER_ROLE_ARN" -f name=PAWLOCAL_CONFIG_READER_ROLE_ARN -f "value=$readerArn"
       } else {
         # A missing variable must be confirmed as HTTP 404; denied access is not absence.
         # Inspect the API response before using POST; stop on any other failure.
         throw 'Confirm HTTP 404 privately, create the exact variable via UI, then rerun.'
       }
       $readbackArn = gh api "$variableEndpoint/PAWLOCAL_CONFIG_READER_ROLE_ARN" --jq '.value'
       if ($LASTEXITCODE -ne 0 -or $readbackArn -ne $readerArn) { throw 'Reader-role variable verification failed.' }
     }
   }
   ```

   For first setup create each missing variable in its exact Environment through **Environment variables → Add variable**, using that matching bootstrap output, then rerun the read-back loop. Set `AWS_REGION` in the matching apply/release Environments to the region used by the owning Terraform roots. Do not set static AWS access keys.
5. After #205 merges, run the direct on-demand audit for the selected environment; while its PR is open use the reviewed exact-branch CI-only test route above. Approve the matching protected job only after reviewing its source/ref. Verify names/statuses and variable read-back; missing generated parameters are expected before #206 and do not prove release readiness. After #206, complete Foundation audit, the separately reviewed runtime-trust bootstrap handoff, Converge enforce and release publication/served OAuth verification in order.

For credential rotation repeat token creation with the same repository/permission restriction, replace both protected Environment secrets through the hidden input, run an authorized audit to verify API access, then revoke the predecessor. Keep rotation records free of credential values.

## Invocation and validation

The planned `.github/workflows/reconcile-environment.yml` supports `workflow_dispatch` and `workflow_call`, selecting exactly development or production. Dispatch defaults to audit. #205 only warns/skips missing sources and explicitly reports that success does not establish release readiness; enforce becomes available in #206.

| Invocation after #206 | Mode | Required-value behavior |
|---|---|---|
| On demand | audit default, enforce selectable | Warn/skip in audit; fail in enforce |
| After successful Foundation apply | audit | Synchronize available values; missing runtime values warn; publication blocked |
| Before Converge/Release planning | enforce | Validate only required inputs consumed by that phase before planning |
| After successful Converge/Release apply | enforce | Validate all required publication values before writes and frontend publication |

In enforce, read and validate every selected source before any write. Missing optional values warn/skip. Invalid mapping/type/format, access denial, API error or read-back mismatch fails in both modes. Do not treat denied reads as absence. Compare ordinary variables before writing, create/update differences, and read back all available mapped destinations including no-ops. For mapped secrets, retrieve internally, encrypt for the destination and verify API success; GitHub cannot return secret plaintext, so never claim equality/read-back. Keep secret payloads out of workflow outputs, artifacts, logs, public reports and frontend snapshots. Reports contain names/statuses only. Multiple writes are not atomic; report partial progress without values and recover by idempotent rerun.

Serialize reconciliation per environment, without a caller holding the same concurrency group as its reusable child. Coordinate apply, reconciliation and publication ordering; cancellation, failed apply, failed enforced validation or failed writes blocks dependent publication. Keep Terraform saved-plan integrity/review, protected apply, development eligibility and production promotion unchanged. Do not add reconciliation-specific commit/hash binding, configuration fingerprints or state-generation evidence machinery.

## Canonical public values

Use actual managed-resource attributes, not guessed identifiers or log parsing. API base is the matching HTTPS API origin plus `/api/v1`; health URL is its `/health` endpoint. Cognito domain is the full HTTPS origin `https://<managed-domain>.auth.<region>.amazoncognito.com`, with no OAuth path. Browser client ID comes from the managed public client (`generate_secret=false`). Redirect is its matching callback URL (`https://<frontend>/auth/callback`), logout is its matching logout URL (`https://<frontend>/`), and scopes are the managed allowed OAuth scopes joined by spaces (`openid email profile` currently). Validate account/environment bindings for IAM ARNs and matching frontend/API origins; never copy between environments. The app uses the client ID and OAuth origin, not the issuer, for hosted login.

In #206 pass verified non-secret frontend values directly from that same successful reconciliation to the build. Updating GitHub vars alone does not refresh a running job's vars context or an old served Vite bundle. Rebuild, publish through the existing approved path, and observe the served sign-in redirect's OAuth host, client ID and callback. A healthy homepage is insufficient evidence.

## Recovery, rotation and cleanup

Rotate the scoped GitHub credential in the protected Environment before expiry, revoke its predecessor after a successful authorized rerun, and verify API access without logging values. A denied token, expired AWS session or partial write requires corrected setup and a fresh idempotent run. If a Terraform apply fails, preserve existing saved-plan rules: inspect partial state, generate/review a fresh normal-refresh plan; never reuse a stale plan.

Missing source, missing state or removed mapping never deletes a destination. Only a confirmed, independently reviewed destroy may clear the exact affected generated targets and dependent runtime variables. Document the exact environment/name cleanup list and successful API responses; reapply recreates owned Strings, then audit/enforce reconciliation repopulates targets before publication. Recovery tests in #206 must cover both environments, partial writes, retry, stale Cognito variables and a stale served bundle.

Every configuration addition/change/removal/rename updates the mapping and inventory in the same PR. Remove obsolete executable YAML entries and retain all original inventory fields plus obsolete date/reason. A rename keeps the old history. Distinguish retirement from confirmed deletion. The legacy cleanup allowlist is recorded in the inventory; prove no current release/recovery consumer remains before exact-name deletion. Never alter same-named plan/apply inputs, unrelated static settings or `development-seed`.
