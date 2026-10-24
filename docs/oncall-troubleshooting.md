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
  python ops/incident-response/generate-profile.py --approval alanlima/pawlocal/issues/269
  ```
  Record the approval comment on the Quota Ledger issue as required by DEC-012.

---

## Layer 6 — Fixer, Candidate CI, and PR Publication

### Symptom: model continuation fails with HTTP 403 or 429

Check **Show quota gateway failure diagnostics** immediately after the fixer/reviewer model step. This always-run step reads at most 64 KiB from the fixed runner-owned diagnostic file, even when the model step failed or the gateway has stopped. An absent file means no diagnostic was recorded; it does not prove that no model request or reservation occurred.

| Diagnostic | Meaning and next action |
|---|---|
| `origin=local`, `code=local_quota_exhausted`, HTTP 403 | Local request/input/output quota refused the call. Inspect `stage` and `reason`; adding API credits cannot change this limit. |
| `origin=local`, `code=local_admission_denied`, HTTP 403 | Request schema, profile, deadline or live-control policy refused admission. Preserve the gate and inspect the reason. |
| `origin=openai`, `code=upstream_http_error`, `upstream_status=429` | OpenAI returned 429. Inspect available `upstream_code`, `upstream_type` and `request_id` to distinguish billing quota from rate limits. The gateway preserves upstream HTTP status; it does not retry the call. |
| `origin=github`, `stage=live_control` | A GitHub live-control read failed. This is not an OpenAI credit failure. |
| `origin=transport`, `code=transport_uncertain`, HTTP 502 before streaming | A socket/network operation failed. `stage` distinguishes header reading, token count, live control and inference; usage may be uncertain. |
| `response_started=true` | Streaming had already returned HTTP 200 before failing. The connection closes; no second HTTP response is appended. Treat partial delivery as uncertain. |

Both successful `oncall_quota_reserved` records and failure records are written to the existing runner-owned diagnostic file and operational stderr. Each record includes `counted_input_tokens` (null before a count is available), `requests_received`, `requests_reserved`, `input_tokens_reserved`, `output_tokens_reserved`, request-body bytes and a `limits` object with the active request/input/output/body ceilings and effective per-turn output cap. A success snapshot includes that call's full conservative reservation; a refusal snapshot leaves prior charges unchanged.

Use the **first** refusal, before client reconnect attempts, to identify the original bound:

| Reason | Exact comparison |
|---|---|
| `per-request input quota exhausted` | `counted_input_tokens > limits.input_per_request` |
| `cumulative input quota exhausted` | `input_tokens_reserved + counted_input_tokens > limits.input_per_role` |
| `request count quota exhausted` | Received requests exceed `limits.requests_per_role`, or all reserved requests are consumed. |
| `request body bound exceeded` | Declared/received body bytes are outside the accepted positive size bound. |
| `cumulative output quota exhausted` | No positive per-turn output allocation remains within the role ceiling. |

Rejected header/body requests can have null counted input and do not imply an upstream model call. Reconnect attempts can reach a later request-count refusal after an earlier input refusal; inspect the first record and the counters, not only the client's final error. These are reservations, not provider-billed usage. CLI token summaries and account-wide usage totals cannot replace per-request accounting. An unexplained test exit 130 is not proof of an application deadlock or a sandbox defect; preserve its actual command, elapsed time and output for separate investigation.

Diagnostics contain fixed classifications and bounded upstream identifiers, not credentials, request/model contents or upstream error messages. Normal operational stdout/stderr is retained. The response carries the same structured classification for the model client. Reservations remain consumed on all failed/uncertain calls.

The allocator reserves `min(output_per_request, output_per_role // requests_per_role)` output tokens per call. A profile with four requests, a 16,000-token per-request ceiling and a 32,000-token role ceiling therefore permits four 8,000-token turns without increasing the envelope. See [profile allocation and rollout](oncall-setup.md#per-turn-output-allocation-301). Consumed incident generations and ledger reservations are not automatically retried or refunded.

The reviewed per-request output bound is 128,000, the [official gpt-5.4-mini maximum](https://developers.openai.com/api/docs/models/gpt-5.4-mini). For the owner-approved 126,000-token allowance with a 2,000-token buffer, 64 calls require `output_per_role=8064000`; keeping the former `4096000` role ceiling still allocates only 64,000 per call. At 2.4M input tokens per role and the approved Standard rates, the two-role reservation is $76.176. Protected profile activation follows reviewed source merge; the $200 monthly/40-run ceilings and the 20-minute deadline remain separate constraints. See [runtime capacity bounds](oncall-setup.md#owner-approved-runtime-capacity-bounds-313-315).

### Switching the incident model to `gpt-5.4-mini`

The profile generator defaults to `gpt-5.4-mini` with matching `750000`/`4500000` rates. Changing only `model` in an existing protected JSON profile does not update token budgets or pricing fields. For another model, the generator requires both reviewed `--input-rate` and `--output-rate` with `--model`; it never silently reuses the default rates. For Standard global pricing reviewed 24 October 2026, use `input_rate=750000` and `output_rate=4500000` (microdollars per million tokens); the former `1100000`/`4400000` values underestimate this model's output rate. Keep the monthly ceiling at `monthly_microdollars=20000000` ($20) and `monthly_runs=20`.

The four 8,000-token turns require the #301 code fix in [PR #302](https://github.com/alanlima/pawlocal/pull/302) to be reviewed and merged. Updating protected profile model/rate fields is a separate owner-reviewed rollout; it does not activate an unmerged code fix or restore consumed incident reservations. See [the detailed profile instructions and official pricing source](oncall-setup.md#switching-the-approved-profile-to-gpt-54-mini) before preparing the complete profile. No live profile is changed by this documentation.

### Symptom: TestClient or asyncio test hangs inside the model sandbox

The [pinned Codex Linux sandbox source](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/linux-sandbox/src/seccomp.rs) blocks `sendto`, including `socket.send` on asyncio's existing local self-pipe. This can leave AnyIO/FastAPI TestClient's portal thread asleep while the calling thread waits. The trusted backend test launcher replaces only this wakeup operation on an existing AF_UNIX/SOCK_STREAM descriptor with `os.write`. It does not enable networking, patch general socket functions, change tests/assertions, or install global Python hooks.

Use the exact backend test command printed in the trusted incident prompt: its immutable launcher lives in the runner-owned dependency directory outside the candidate workspace. The adapter affects only that pytest process. Closed-loop/full-buffer error behavior is preserved; unknown socket types use the original implementation. Independent candidate regression and full-suite checks continue to invoke ordinary pytest outside Codex's sandbox as the isolated model UID. No test is skipped or its outcome altered.

Credential-free verification runs real TestClient requests under the pinned CLI `:workspace` profile on hosted Python 3.12 and confirms AF_INET creation remains denied. Local diagnosis additionally proved the same unmodified PawLocal regression fails on the original sort bug and passes with the candidate sort correction. An exit 130 alone remains insufficient evidence: inspect the actual command, output, stack and counters before attributing a new failure.

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
