# On-call responder troubleshooting guide

This guide documents verified failure modes, root causes, diagnosis commands, and resolutions across the automated incident responder lifecycle (`incident-responder.yml`).

For step-by-step onboarding and setup instructions, see the [On-call responder setup guide](oncall-setup.md).

---

## Incident lifecycle at a glance

```text
Layer 1: Webhook Ingress (Grafana alert → Lambda Function URL)
    ↓
Layer 2: Workflow Trigger (Lambda → GitHub Actions Dispatch App)
    ↓
Layer 3: Preflight Readiness (Readiness token, main branch ruleset policy)
    ↓
Layer 4: Preflight Admission (Grafana Alertmanager check, ledger quota, issue claim)
    ↓
Layer 5: Remediation Loop (Codex fixer, candidate CI, fresh review, publisher PR)
    ↓
Layer 6: Deployment & Recovery (Squash merge, DEV deployment, Prometheus recovery, PROD promotion)
```

---

## Summary of common failure modes

| Layer | Symptom | Immediate cause | Resolution |
|---|---|---|---|
| Ingress | `HTTP 401` from Lambda | HMAC signature mismatch or timestamp skew (> 300s) | Match SSM HMAC secret with Grafana contact point; verify UTC timestamp |
| Ingress | `HTTP 403` from Lambda | Alert payload contains unapproved `service` or `alertname` | Ensure labels match SSM `/pawlocal/<env>/config/oncall/allowed-services` |
| Dispatch | `HTTP 502` from Lambda | GitHub Dispatch App auth failure or missing Actions permission | Check SSM Dispatch App PEM key, installation ID, and repository permissions |
| Readiness | `ruleset id=...: effective PR policy requires unsupported/human gates` | Ruleset requires human reviews or non-squash merge | Configure `Protect Main Branch` with 0 human reviews, squash-only, thread resolution |
| Readiness | `unreviewed effective main policy type` | Unknown ruleset rule type configured on `main` | Restrict ruleset rules to `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks` |
| Admission | `urllib.error.HTTPError: HTTP Error 401: Unauthorized` | Invalid Grafana query token or wrong token type | Ensure `PAWLOCAL_GRAFANA_QUERY_TOKEN` is a Grafana Stack Service Account token (`glsa_`), not a Cloud Access Policy (`glc_`) |
| Admission | `admitted=false` / `no firing alerts selected for admission` | Synthetic test alert not active in Grafana Alertmanager | **Expected behavior for synthetic tests**; to run the full loop, test with an active firing alert |
| Quota | `trusted ledger issue missing` or issue closed | Emergency stop engaged or ledger issue unconfigured | Reopen or configure the Quota Ledger issue (#269) |
| Quota | `approved_month` mismatch or profile expired | Monthly model profile expired or month rolled over | Re-issue profile via `ops/incident-response/generate-profile.py` |
| Recovery | Recovery settling timeout | Health check failing or Grafana alert rule still firing | Inspect application logs and Prometheus alert rule evaluation |
| Promotion | Run stops after DEV recovery without PROD promotion | `PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED` unset in PROD | **Expected DEV-only behavior**; enable production variables when authorized |

---

## Layer 1 — Webhook Ingress (Lambda Receiver)

The Lambda receiver validates HMAC signatures, checks alert allowlists, and mints an installation token to dispatch `incident-responder.yml`.

### Symptom: `HTTP 401 Unauthorized`

* **Cause 1: HMAC signature mismatch.**
  The HMAC SHA-256 signature calculated over `<timestamp>:<raw_body>` does not match the secret in SSM parameter `/pawlocal/<env>/secrets/grafana/webhook-hmac`.
  * **Diagnosis**:
    ```powershell
    $Secret = aws ssm get-parameter --name "/pawlocal/development/secrets/grafana/webhook-hmac" --with-decryption --query Parameter.Value --output text
    ```
    Confirm that the same 32-byte hex secret is entered in the Grafana Contact Point under **Optional Webhook settings** → **HMAC setup** → **Secret**.
* **Cause 2: Timestamp header skew.**
  The Lambda receiver enforces a 300-second window on `x-grafana-alerting-timestamp`. Skewed clocks or stale timestamps result in `401`.
  * **Diagnosis**: Verify system clock uses UTC:
    ```powershell
    [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    ```

### Symptom: `HTTP 403 Forbidden`

* **Cause**: The incoming alert does not match the allowlist.
  The receiver drops alerts whose `service` is not in SSM `/pawlocal/<env>/config/oncall/allowed-services` (default `["pawlocal-api"]`), or whose `alertname` is not in `/pawlocal/<env>/config/oncall/allowed-alerts` (default `["pawlocal-development-search-detail-failure"]`).
* **Diagnosis**: Inspect CloudWatch logs for `/aws/lambda/pawlocal-<env>-oncall-receiver`.
* **Fix**: Ensure the firing Grafana alert rule attaches `service = "pawlocal-api"` and the approved `alertname`.

---

## Layer 2 — GitHub Workflow Dispatch

### Symptom: `HTTP 502 Bad Gateway`

* **Cause**: The Lambda receiver failed to authenticate with the GitHub API or could not dispatch `incident-responder.yml`.
* **Checklist**:
  1. **SSM Private Key**: Parameter `/pawlocal/<env>/secrets/oncall/dispatch-app-private-key` must contain the complete PEM private key (`-----BEGIN RSA PRIVATE KEY-----...`).
  2. **Installation ID**: Parameter `/pawlocal/<env>/config/oncall/dispatch-app-installation-id` must match the actual Installation ID where the Dispatch App is installed on `alanlima/pawlocal`.
  3. **Repository Permissions**: The Dispatch App must have repository permission **Actions: Read & write**. (It needs no contents, PR, or administration permissions).
  4. **Installation Scope**: Ensure the App is installed on the specific repository (`alanlima/pawlocal`).

---

## Layer 3 — Preflight Readiness & Ruleset Validation

Preflight runs inside GitHub Actions on `main`. It mints an elevated readiness token via the Publisher App (`ops/incident-response/publisher-token.mjs`) to inspect repository rulesets, ensuring that automated squash-merging can occur without human bypass or branch protection circumvention.

### Symptom: `ruleset id=...: effective PR policy requires unsupported/human gates`

* **Cause**: The `Protect Main Branch` ruleset requires manual review gates that prevent the automated publisher from squash-merging.
* **Requirements**:
  Under the approved incident architecture (DEC-012 / Issue #245):
  * `required_approving_review_count`: must be `0` (fresh review is performed by an automated Codex reviewer during the incident run).
  * `require_code_owner_review`: must be `false`.
  * `required_review_thread_resolution`: must be `true`.
  * `allowed_merge_methods`: must be exactly `["squash"]`.
  * `require_last_push_approval`: must be `false`.

### Symptom: Ruleset `bypass_actors` or least-privilege token errors

* **Background (Issue #279)**:
  GitHub's REST API omits `bypass_actors` from GET responses unless the token holds repository administration *write* access. To maintain least privilege, the Publisher App holds only `Administration: Read`.
* **Resolution**:
  `ops/incident-response/admission.py` accepts omitted `bypass_actors` and verifies `current_user_can_bypass == "never"` for itself. Ensure zero bypass actors are configured on the ruleset in the GitHub UI.

### Symptom: Elevated token minting fails in `publisher-token.mjs`

* **Cause**: The Publisher App credentials in GitHub Secrets are missing or lack required permissions.
* **Checklist**:
  * Environment `oncall-development` must have secret `PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY` and variables `PAWLOCAL_ONCALL_PUBLISHER_APP_ID`, `PAWLOCAL_ONCALL_PUBLISHER_INSTALLATION_ID`.
  * The Publisher App must have permissions:
    * **Administration**: `Read` (to inspect rulesets).
    * **Contents**, **Pull requests**, **Issues**, **Commit statuses**: `Read & write`.

---

## Layer 4 — Preflight Admission & Alert Verification

Admission connects to Grafana Alertmanager (`/api/alertmanager/grafana/api/v2/alerts`) using `PAWLOCAL_GRAFANA_QUERY_TOKEN` to verify that the reported incident alert is actively firing.

### Symptom: `urllib.error.HTTPError: HTTP Error 401: Unauthorized`

* **Cause 1: Environment Secret Precedence (Repository vs. Environment Secret)**
  * In GitHub Actions, secrets defined on an Environment (e.g. `oncall-development`) **override** repository-level secrets of the same name.
  * If `Operations · Verify Grafana access` passes using the repository secret, but `incident-responder.yml` fails with `401`, check the environment secret in **Settings** → **Environments** → **`oncall-development`** → **`PAWLOCAL_GRAFANA_QUERY_TOKEN`**.
* **Cause 2: Wrong Token Type (Cloud Access Policy vs. Stack Service Account Token)**
  * As documented in `docs/specs/monitoring-secret-lifecycle.md`, Grafana Cloud Access Policy tokens (`glc_...` created in `grafana.com`) are for Cloud Portal management and telemetry ingestion. They **cannot** authenticate against Grafana Stack API endpoints (`https://<stack>.grafana.net/api/...`).
  * The query token **must** be a Grafana Stack Service Account token (`glsa_...`), created inside the Grafana web instance:
    1. Log in to `https://alanlima.grafana.net`.
    2. Go to **Administration** → **Users and access** → **Service accounts**.
    3. Select or create a service account with the **Viewer** role.
    4. Generate a token (starts with `glsa_`).
* **Verification**:
  Test the token locally before saving to GitHub Secrets:
  ```powershell
  $Token = "glsa_your_token_here"
  Invoke-RestMethod -Uri "https://alanlima.grafana.net/api/alertmanager/grafana/api/v2/alerts" -Headers @{ Authorization = "Bearer $Token" }
  ```
  It must return HTTP `200` with JSON (empty `[]` or active alert entries).

### Symptom: `[admission] Preflight completed: no firing alerts selected for admission` (`admitted=false`)

* **Explanation**: This is **expected, correct behavior** when sending a synthetic test alert (such as the curl command from Step 10 of `oncall-setup.md` with fingerprint `0123456789abcdef01234567`).
* `admission.py` contacts Grafana Alertmanager, searches for a firing alert matching the test alert's fingerprint, and finds none.
* It safely exits with `admitted=false` without creating an issue, reserving quota, or invoking model jobs.
* **To run the full loop**: The alert must match an actual active alert currently firing in Grafana.

---

## Layer 5 — Quota Ledger and Monthly Profile

### Symptom: `trusted ledger issue missing`

* **Cause**: The Quota Ledger issue specified in `PAWLOCAL_ONCALL_QUOTA_ISSUE` (default `#269`) is closed, inaccessible, or has had its initial header modified.
* **Emergency Stop Mechanism**: Closing the Quota Ledger issue acts as an immediate runtime kill switch. All running jobs inspect the issue before executing mutations and immediately halt if closed.
* **Fix**: Reopen the issue or verify that the issue body begins with:
  ```markdown
  <!-- pawlocal-oncall-quota-ledger -->
  ```

### Symptom: `approved_month` mismatch or profile expired

* **Cause**:
  1. The calendar month rolled over (e.g. from October to November), but `PAWLOCAL_ONCALL_MODEL_PROFILE` still specifies the old month.
  2. The profile `expires_at` timestamp is older than 31 days.
* **Fix**:
  Re-generate the monthly profile and update `PAWLOCAL_ONCALL_MODEL_PROFILE` in GitHub Environments:
  ```powershell
  python ops/incident-response/generate-profile.py --issue 269
  ```
  Record the approval comment on the Quota Ledger issue as required by DEC-012.

---

## Layer 6 — Fixer, Candidate CI, and PR Publication

### Symptom: `candidate changes touch non-allowlisted paths`

* **Cause**: The Codex fixer agent generated diffs outside allowlisted application boundaries.
* **Policy**: Under DEC-012, automated incident repairs are strictly restricted to application source paths (`frontend/`, `backend/`). Modifications to workflows, Terraform, IAM, scripts, or documentation are rejected and fail closed.

### Symptom: `403 Resource not accessible by integration` during PR creation

* **Cause**: The Publisher App installation token does not have write permissions for pull requests or issues.
* **Fix**: Verify in **GitHub App Settings** → **Permissions** that `Pull requests` and `Issues` are set to **Read and write**.

---

## Layer 7 — Deployment, Promotion, and Recovery Verification

### Symptom: Recovery verification timeout (`recovery rule settling` or `stale evaluation`)

* **Cause**: After squash-merging and deploying to `development`, `ops/incident-response/recovery.py` observes the place discovery journey (`/health`, `/places`, `/places/{id}`) and Grafana Prometheus rule state. If the rule continues to fire after the settling window, recovery fails.
* **Checklist**:
  1. Inspect the deployment run in GitHub Actions to confirm new container image was deployed.
  2. Check backend health endpoint (`/health`).
  3. Verify that Grafana alert rule evaluation interval has passed and Prometheus state returned to `inactive` / `Normal`.

### Symptom: Run stops cleanly after DEV recovery without promoting to PROD

* **Explanation**: This is **by design** when `oncall-production` is not fully enabled:
  * In `oncall-production`, variable `PAWLOCAL_ONCALL_ENABLED` must be `true`.
  * In `oncall-production`, variable `PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED` must be `true`.
  * If either is absent or false, the incident workflow verifies development recovery and safely terminates without performing production promotion.
