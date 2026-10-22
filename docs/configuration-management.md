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
4. Set `PAWLOCAL_CONFIG_READER_ROLE_ARN` in **Environment variables** for both `development` and `development-apply`, using their actual matching bootstrap output; repeat for production. Set `AWS_REGION` to the owning root's region. Read each variable back, for example `gh api repos/alanlima/pawlocal/environments/development-apply/variables/PAWLOCAL_CONFIG_READER_ROLE_ARN --jq '.value'`. Compare privately with the output; stop on mismatch or denied access. Automatic reader-ARN handoff remains #191.
5. Preserve required reviewers and branch policies. Before synchronization, explicitly create `production-destroy-prepare` and `production-destroy` with the owner reviewer and main-only branch policy; set their operator inputs `AWS_REGION` and `PAWLOCAL_TF_STATE_BUCKET`. Never create targets implicitly through writes. These targets need no token/reader ARN; setup does not authorize destroy.

One reconciliation job uses the matching protected `<environment>-apply` Environment for approval, token and exact repository-ID-qualified OIDC reader trust. Readers access only approved matching-environment keys, without writes, state access or cross-environment access. No current source requires decryption. See the inventory/issue for actual setup and runtime status.

## Run and verify

The callable/on-demand `reconcile-environment.yml` selects development or production. Audit is the default; choose enforce to require all selected values before synchronization/publication. Missing sources warn/skip in audit, which synchronizes available values but **does not establish release readiness**.

The script is `ops/configuration/reconcile.py`; install its pinned `requirements.txt` first. It validates the manifest and existing destination Environments, then reports names/statuses only. The workflow exposes the scoped token only to protected credential/mutation steps and creates no payload artifacts. Test locally with `uv run --with-requirements ops/configuration/requirements.txt python -m unittest discover -s ops/configuration/tests -v`. Prefer the protected workflow for operations so approval and ordering are enforced.
Reusable callers pass only the required named `PAWLOCAL_CONFIG_GITHUB_TOKEN` secret; the matching protected Environment supplies its value. A nonempty check runs before AWS access. No repository-global credential copy is needed.

For an open-PR test, use the existing CI-only `ci.yml` opt-in development call from the exact reviewed feature branch. Temporarily allowlist only that branch in `development-apply`, retain reviewer approval, then remove the allowance after merge. Verify direct dispatch after merge.

| Invocation | Mode | Required-value behavior |
|---|---|---|
| On demand | Audit default; enforce selectable | Warn/skip or fail according to mode |
| After Foundation apply | Audit | Missing runtime values may be expected; publication blocked |
| Before Converge/Release planning | Enforce | Check only required inputs consumed by that phase before planning |
| After Converge/Release apply | Enforce | Validate required publication values before writes/publication |

Enforce reads/validates all selected sources before writes. Optional absence warns/skips. Invalid mappings/types/formats, access denial, API errors and read-back mismatch fail in both modes. Run one reconciliation at a time per environment. Caller and called workflow must use different lock groups. Failed/cancelled apply or failed reconciliation blocks publication. Preserve saved-plan review/integrity, the separate bootstrap runtime-trust handoff and production eligibility/promotion controls.

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

Only these six fields are allowed. `secret` defaults false; `validations` defaults empty. Only `{environment}` may be substituted, after validating development/production input. Each destination has its own entry. Targets are matching release/plan/apply Environments, plus exactly `production-destroy-prepare`/`production-destroy` for the production apply-role ARN, account ID and plan bucket. No development-destroy/seed target is allowed.

Reject unknown fields/placeholders/rules, duplicate destinations, cross-environment sources and inconsistent classification/type/secret flags. Never discover arbitrary keys. Ownership and lifecycle selection belong in inventory/orchestration, not extra YAML metadata. Actions configuration requiring synchronization updates mapping and inventory together; unrelated local/application configuration does not. Remove obsolete executable mappings; preserve original fields, obsolete date/reason and separate deletion status in history, including the old entry after a rename.

## Values and recovery

Variables use compare-before-write and read-back, including no-ops. Secrets use encrypted API writes; GitHub cannot return plaintext for equality checks. Keep payloads out of Terraform resources/data/state/outputs, command arguments, workflow outputs/artifacts/logs, public reports and frontend snapshots. Reports contain names/statuses only; do not persist temporary tokens. No active secret mapping is required today.

Use actual managed attributes: API HTTPS origin plus `/api/v1`, health `/health`; Cognito full HTTPS origin `https://<managed-domain>.auth.<region>.amazoncognito.com`; managed public client ID; managed callback `/auth/callback`, logout `/`, and space-joined scopes (currently `openid email profile`). Validate account/environment bindings and matching frontend/API origins; never copy across environments.

Pass the same reconciliation's verified public values directly to the build, rebuild/publish, then observe the served OAuth host/client/callback/scopes. Variable read-back or a healthy homepage alone is insufficient. Do not introduce reconciliation-specific commit/hash binding, fingerprints or state-generation machinery.

Writes are not atomic. Correct partial failures and rerun; completed writes should be checked and skipped. Failed Terraform applies require a fresh reviewed normal-refresh plan. Missing source/state/mapping never deletes targets. Only confirmed reviewed destroy clears exact affected generated targets/dependent runtime variables; reapply must republish/reconcile before publication. Legacy cleanup needs consumer proof and exact environment/name deletion from the inventory; preserve same-named plan/apply inputs, unrelated static/certificate settings and `development-seed`.

Test both environments: partial writes and safe reruns, missing optional/required values, replacement Cognito settings, a stale served bundle, and confirmed destroy/reapply recovery.

Before token expiry, create its scoped replacement, replace both protected secrets through hidden input, run an authorized audit, then revoke the predecessor. Keep rotation records free of values.

For approved legacy cleanup, dispatch the reconciliation workflow with `operation=legacy-cleanup` and exact `confirmation=CLEAN legacy <environment>`. Review the protected job and its consumer checks before approval. It deletes only the inventory's legacy release names; static plan/apply and seed settings are untouched. Destroy cleanup is internal to the existing reviewed destroy workflow after successful apply and empty-state verification. Never substitute missing sources for that confirmation.
