# Configuration management

This guide covers Parameter Store values synchronized to GitHub Actions Environments. See the [inventory](configuration-inventory.md) for exact keys, destinations and owners, and [Terraform operations](terraform-greenfield-operations.md) for plan/apply approvals.

## Set up access

1. Apply the reader-role bootstrap changes only after independent review of the exact saved plan and owner authorization. Read `terraform -chdir=infra/terraform/iam-bootstrap output -json configuration_reader_role_arns` after apply. This output is introduced by #205; do not guess ARNs or use static AWS keys.
2. Create a fine-grained token in GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**. Select owner `alanlima`, **Only select repositories → pawlocal**, a bounded expiration and **Environments: Read and write**. Metadata read is automatic. Record the expiry in your credential manager. See [GitHub's instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
3. Add `PAWLOCAL_CONFIG_GITHUB_TOKEN` under repository **Settings → Environments → development-apply → Environment secrets**; repeat for `production-apply`. **Secrets and variables → Agents** is a separate credential domain. Alternatively use hidden prompts:

   ```powershell
   gh secret set PAWLOCAL_CONFIG_GITHUB_TOKEN --repo alanlima/pawlocal --env development-apply
   gh secret set PAWLOCAL_CONFIG_GITHUB_TOKEN --repo alanlima/pawlocal --env production-apply
   ```

   Never put the token in chat, files or command arguments. Verify names only with `gh api repos/alanlima/pawlocal/environments/development-apply/secrets --jq '.secrets[].name'`, then repeat for production. Ordinary `GITHUB_TOKEN` is insufficient.
4. Set `PAWLOCAL_CONFIG_READER_ROLE_ARN` in **Environment variables** for both `development` and `development-apply`, using their actual matching bootstrap output; repeat for production. Set `AWS_REGION` to the owning root's region. Read each variable back, for example `gh api repos/alanlima/pawlocal/environments/development-apply/variables/PAWLOCAL_CONFIG_READER_ROLE_ARN --jq '.value'`. Compare privately with the output; stop on mismatch or denied access. The owner-operated [setup script](../ops/iam-bootstrap/README.md) provides explicit `publish-reader-roles` for initial setup or reader-role recreation, with four-target comparison and read-back. Bootstrap Actions have no separate publication job; existing reconciliation continues handling its approved mapping.
5. Preserve required reviewers and branch policies. Before synchronization, explicitly create `production-destroy-prepare` and `production-destroy` with the owner reviewer and main-only branch policy; set their operator inputs `AWS_REGION` and `PAWLOCAL_TF_STATE_BUCKET`. Never create targets implicitly through writes. These targets need no token/reader ARN; setup does not authorize destroy.

One reconciliation job uses the matching protected `<environment>-apply` Environment for approval, token and exact repository-ID-qualified OIDC reader trust. Readers access only approved matching-environment keys, without writes, state access or cross-environment access. No current source requires decryption. See the inventory/issue for actual setup and runtime status.

## Public reader authorization (#237)

The configuration reader uses the configured account/region parameter scope and requires all three authorization tags: `project=<project_name>`, matching `environment`, and `configuration-access=github-public`. Public String producer tags are Terraform-owned; mapping growth does not require enumerating more reader ARNs. Producer write inventories remain exact and separate. No secret/KMS, tagging, discovery, history or by-path permission is added. A public tag on a private parameter is an access-control defect; variables and naming alone do not restrict the tag-based policy.

Roll out application public tags under the old reader policy **before** the bootstrap tags/policy switch. Coordinate independent states and pause dependent callers for the transition; see the [ordered rollout/rollback and missing-resource limitation](../infra/terraform/iam-bootstrap/POLICY_DESIGN.md#ordered-rollout-and-rollback-237). The Terraform workflow uses warning-only reconciliation before and after apply. If synchronization cannot return verified configuration, its existing matching protected Environment variables supply Terraform inputs; normal required-input validation and exact-plan approval still apply. This allows a reviewed Converge plan to repair producer tags without rerunning Foundation and disabling runtime resources. No apply is authorized here. A missing untagged resource can produce `AccessDenied`; preserve that error rather than reporting it as missing. The requested warning/skip behavior remains a separate #223/#233 existence-design/live-verification dependency; this prerequisite does not claim it is solved.

## Run and verify

The callable/on-demand `reconcile-environment.yml` selects development or production. Audit is the default; choose enforce to require all selected values before synchronization/publication. Missing sources warn/skip, and synchronization errors warn by default in both modes. Neither a zero exit status nor a successful warning-only workflow establishes release readiness. Use `--fail-on-error` on the script or `fail_on_error: true` on the existing workflow only when the caller explicitly requires synchronization failure to block it. This is an error-policy switch, not another reconciliation mode. The manual dispatch form defaults `fail_on_error` to true for an explicit operator-run verification; reusable calls and the script remain warning-only by default, and Terraform explicitly selects warning-only behavior.

Open the job's **Summary** for destination counts, changed GitHub Environments and the full mapping grouped by target. For example, a fully configured development no-op shows **31 unchanged, 37 not selected; changed Environments: None**. Missing sources/targets appear as warnings. Cleanup has a separate exact-target table.

Variable results require matching readback. Secret writes show **write accepted**; GitHub does not return secret values or verify unchanged content. Failed or incomplete reports distinguish confirmed changes from accepted-but-unverified or possible writes. Completed writes remain after a failure; rerun after fixing the cause. Cancellation or runner loss can prevent a final report, so missing rows never prove no writes occurred.

The script is `ops/configuration/reconcile.py`; install its pinned `requirements.txt` first. It validates the manifest and existing destination Environments, then reports names/statuses only. The workflow exposes the scoped token only to protected credential/mutation steps and creates no payload artifacts. Test locally with `uv run --with-requirements ops/configuration/requirements.txt python -m unittest discover -s ops/configuration/tests -v`. Prefer the protected workflow for operations so approval and ordering are enforced.
Reusable callers pass only the required named `PAWLOCAL_CONFIG_GITHUB_TOKEN` secret; the matching protected Environment supplies its value. A nonempty check runs before AWS access. No repository-global credential copy is needed.

For an open-PR test, use the existing CI-only `ci.yml` opt-in development call from the exact reviewed feature branch. Temporarily allowlist only that branch in `development-apply`, retain reviewer approval, then remove the allowance after merge. Verify direct dispatch after merge.

| Invocation | Mode | Required-value behavior |
|---|---|---|
| On demand | Audit default; enforce selectable | Warn/skip or fail according to mode |
| After Foundation apply | Audit | Missing runtime values may be expected; publication blocked |
| Before Converge/Release planning | Enforce | Check only required inputs consumed by that phase before planning |
| After Converge/Release apply | Enforce | Validate required publication values before writes/publication |

Enforce reads/validates all selected sources before writes. Optional absence warns/skips. Invalid mappings/types/formats, access denial, API errors and read-back mismatch stop synchronization in both modes. Operational errors remain visible and the report remains failed/incomplete; by default the process warns and returns zero. Explicit `--fail-on-error` returns nonzero. Failed synchronization never exposes verified configuration or release snapshot workflow outputs. Run one reconciliation at a time per environment. Caller and called workflow must use different lock groups. Failed/cancelled apply blocks publication. Release consumers separately validate their required same-run snapshot; a warning-only reconciliation does not authorize publication. Preserve saved-plan review/integrity, the separate bootstrap runtime-trust handoff and production eligibility/promotion controls.

## Naming

Use `/pawlocal/<scope>/<classification>/<component>/<setting>`: five nonempty segments after the leading slash.

| Segment | Meaning | Common values |
|---|---|---|
| `pawlocal` | Fixed application namespace | Always `pawlocal` |
| `scope` | Owner/consumer environment | `development`, `production`; `shared` only for values used by both environments (none currently) |
| `classification` | Parameter type/handling | `config` = non-secret String; `secrets` = SecureString |
| `component` | Functional area | `iam` roles; `aws` account; `terraform` plan storage; `frontend` website/CDN; `api` endpoints; `auth` Cognito |
| `setting` | Stable descriptive name | `client-id`, `base-url`, `runtime-role-arn`; lowercase kebab-case, no resource/account IDs or release versions |

Bootstrap owns generated IAM/account/plan-bucket Strings; each application state owns its generated application Strings. Inventory existing keys/ownership before rollout. Unknown keys or duplicate ownership block the affected environment; never overwrite, import or adopt them. No unmanaged parameters are currently needed.

## Mapping

#205 introduces `ops/configuration/parameter-mapping.yaml`:

```yaml
mappings:
  - store_key: /pawlocal/{environment}/config/auth/client-id
    environment: [development, production]
    github_environment: "{environment}"
    env_name: VITE_COGNITO_CLIENT_ID
    secret: false
    validations: [required]
```

Only these six fields are allowed. `secret` defaults false; `validations` defaults empty. Only `{environment}` may be substituted, after validating development/production input. Each destination has its own entry. Targets are matching release/plan/apply and exact `oncall-{environment}` Environments, plus exactly `production-destroy-prepare`/`production-destroy` for the production apply-role ARN, account ID and plan bucket. No development-destroy/seed target is allowed.

Reject unknown fields/placeholders/rules, duplicate destinations, cross-environment sources and inconsistent classification/type/secret flags. Never discover arbitrary keys. Ownership and lifecycle selection belong in inventory/orchestration, not extra YAML metadata. Actions configuration requiring synchronization updates mapping and inventory together; unrelated local/application configuration does not. Remove obsolete executable mappings; preserve original fields, obsolete date/reason and separate deletion status in history, including the old entry after a rename.

## Values and recovery

Variables use compare-before-write and read-back, including no-ops. Secrets use encrypted API writes; GitHub cannot return plaintext for equality checks. Keep payloads out of Terraform resources/data/state/outputs, command arguments, workflow outputs/artifacts/logs, public reports and frontend snapshots. Reports contain names/statuses only; do not persist temporary tokens. No active secret mapping is required today.

Use actual managed attributes: the matching frontend HTTPS origin plus `/api/v1` for the API and `/api/health` for public health, published only when the backend is deployed. Under [DEC-018](decisions.md#dec-018--shared-cloudfront-application-entry-point-346), production uses `https://pawlocal.<domain>` and development uses `https://pawlocal-dev.<domain>` for frontend, API and public health. Require the exact matching environment/domain and paths; reject separate API hosts and foreign or cross-environment bindings. Backend `/health` remains a Lightsail health-check endpoint and is not a public CloudFront API behavior. Cognito uses its full HTTPS origin `https://<managed-domain>.auth.<region>.amazoncognito.com`, managed public client ID, managed callback `/auth/callback`, logout `/`, and space-joined scopes (currently `openid email profile`). Never copy across environments.

Pass the same reconciliation's verified public values directly to the build, rebuild/publish, then observe the served OAuth host/client/callback/scopes. Variable read-back or a healthy homepage alone is insufficient. Do not introduce reconciliation-specific commit/hash binding, fingerprints or state-generation machinery.

Writes are not atomic. Correct partial failures and rerun; completed writes should be checked and skipped. Failed Terraform applies require a fresh reviewed normal-refresh plan. Missing source/state/mapping never deletes targets. Only confirmed reviewed destroy clears exact affected generated targets/dependent runtime variables; reapply must republish/reconcile before publication. Legacy cleanup needs consumer proof and exact environment/name deletion from the inventory; preserve same-named plan/apply inputs, unrelated static/certificate settings and `development-seed`.

Test both environments: partial writes and safe reruns, missing optional/required values, replacement Cognito settings, a stale served bundle, and confirmed destroy/reapply recovery.

Before token expiry, create its scoped replacement, replace both protected secrets through hidden input, run an authorized audit, then revoke the predecessor. Keep rotation records free of values.

The reconciliation workflow copies the single reviewed YAML mapping. Missing Parameter Store values or destination Environments warn and skip; access errors stop synchronization with a warning unless `fail_on_error` is explicitly enabled. It never creates GitHub Environments. Existing on-call Environments must restrict deployments to exactly the `main` branch before any source read or write. Release consumers separately check their required values.

Destroy cleanup remains internal to the protected destroy workflow through `cleanup-destroyed-configuration.yml`, after successful apply and empty-state verification. Its exact confirmation is not a public reconciliation input. Legacy cleanup remains a separately reviewed internal helper operation.

An actual `ParameterNotFound` response is warned and skipped. Under tag-based IAM, an absent parameter or absent authorization tag may instead produce `AccessDenied`; that behavior requires live verification under the exact reader role. AccessDenied remains an operational error, reported as a warning by default or a failing exit when `--fail-on-error` is selected. This change adds no metadata enumeration permission or missing-resource inference.
