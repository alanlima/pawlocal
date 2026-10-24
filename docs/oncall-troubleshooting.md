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

The reviewed per-request output bound is 128,000, the [official gpt-5.4-mini maximum](https://developers.openai.com/api/docs/models/gpt-5.4-mini). For the owner-approved 126,000-token allowance with a 2,000-token buffer, 64 calls require `output_per_role=8064000`; keeping the former `4096000` role ceiling still allocates only 64,000 per call. At 2.4M input tokens per role and the approved Standard rates, the two-role reservation is $76.176. Protected profile activation follows reviewed source merge; the $300 monthly/40-run ceilings and the 20-minute deadline remain separate constraints. See [runtime capacity bounds](oncall-setup.md#owner-approved-runtime-capacity-bounds-313-315).

### Switching the incident model to `gpt-5.4-mini`

The profile generator defaults to `gpt-5.4-mini` with matching `750000`/`4500000` rates. Changing only `model` in an existing protected JSON profile does not update token budgets or pricing fields. For another model, the generator requires both reviewed `--input-rate` and `--output-rate` with `--model`; it never silently reuses the default rates. For Standard global pricing reviewed 24 October 2026, use `input_rate=750000` and `output_rate=4500000` (microdollars per million tokens); the former `1100000`/`4400000` values underestimate this model's output rate. The original conservative profile uses `monthly_microdollars=20000000` ($20) and `monthly_runs=20`; the temporary owner-approved capacity profile described above uses $300 and 40 runs.

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

### Symptom: candidate seal rejects otherwise approved edits

Backend package builds create `build/` and egg-info metadata beside their source. The trusted runner installs from a separate runner-owned backend source copy, preserving the archived comparison baseline. Independent checks already use a separate dependency-source archive. These build outputs are not added to the candidate allowlist or ignored by the exporter.

An export refusal reports a fixed reason (`empty`, `excessive_files`, `outside_approved_paths` or `source_deletion`), total changed/outside/deleted counts, and at most 20 escaped relative paths of 240 characters each. Inspect that inventory before attributing the failure to model edits or test caches. Contents and model payloads are never included. An excessive candidate can also contain outside/deleted paths; the separate counts preserve that evidence. Symlink and source-deletion guards remain enforced.

### Symptom: exporter reports every baseline file deleted

This can indicate failed inspection rather than actual model deletions. The archive root is private (`0700`), and copying it preserves that mode before ownership changes to the isolated model UID. After quiescing model processes, trusted seal and review seal reclaim only the fixed candidate root directory for the runner, using nonrecursive `chown --no-dereference`. A bounded regular review report is likewise reclaimed so a normal `0600` report remains readable. Contents, modes, nested ownership and model privileges remain unchanged.

Missing, symlink or non-directory roots and unreadable nested directories explicitly fail inspection; they are never treated as an empty tree. A model-created private nested directory or unreadable source file requires escalation, not recursive permission changes. The separately owner-approved temporary capacity ceiling is $300 for 40 monthly runs with the unchanged $76.176 two-role envelope. Consumed reservations remain charged, and source changes do not activate a protected profile or retry a generation.

### Symptom: trusted checks cannot enter source cwd or read regression output

Affected, main and candidate check roots use mode `0750`, owned by the isolated test UID with the runner GID. This permits both users to traverse the disposable sources without exposing private archives or granting the runner write access. The check-work parent remains runner-owned and not model-writable. Comparison/dependency archives and candidate Git metadata remain private (`0700`).

After each regression process exits, trusted code quiesces residual test processes before reading its report. Only the six fixed backend XML/frontend JSON paths are eligible for nonrecursive runner ownership reclamation. Parent components must be real directories, and the runner-owned container must not be group/world writable. Reports must be bounded regular files with one hard link; symlinks, hard links and oversized reports fail closed. Reads reject symlink components and retain the actual pytest/Vitest exit status and collected failure counts. Normal `0600` reports are supported without relaxing their permissions.

Incident frontend validation uses the trusted `build:check` script for the same TypeScript/Vite compile used by ordinary `build`. Ordinary release `build` retains its cloud-configuration prebuild and release-bundle postbuild validators. The isolated compile needs no deployment identity or release credentials and publishes no artifact. A credential-free hosted fixture covers actual seal, fail on affected/current main, pass on candidate/full backend tests, real Vitest JSON reports, normal frontend checks/compile, and fresh review readback/binding.

### Symptom: functional checks pass but required backend CI reports Ruff I001

A generated regression can demonstrate the application failure yet fail required `ruff check .` because its imports are not formatted correctly. Trusted validation runs the required backend quality sequence **before any authentic regression executes**: Ruff, baseline DSQL lint, actual candidate search SQL rendering/lint, Alembic upgrade and complete pytest including PostgreSQL integration tests. This mirrors required CI's lint-before-test ordering; it does not claim candidate-owned sources remain immutable after arbitrary test code executes. A malformed-import candidate produces no eligible checks receipt.

Tools and dependency metadata (`[test,dsql-prototype]`) come from immutable main. The fixer can run preinstalled Ruff and correct only its allowlisted files before sealing; the fresh reviewer runs check only and reports findings without changing the candidate. Trusted validators never auto-fix sealed bytes. The actual pinned Codex sandbox fixture verifies Ruff I001, a scoped import fix with unchanged Python AST, and a clean recheck while external network sockets remain denied.

### Disposable backend quality and release validation

Only trusted check/review and quality-fixture jobs have a disposable PostgreSQL service bound to `127.0.0.1:5432`, using public test credentials. The harness projects only the exact fixed test URL into its unprivileged test process; cloud database URLs, host aliases and query overrides are rejected. Full-suite JUnit must show all three known PostgreSQL integration tests passed without skips. This requires no deployment, AWS, Grafana or production-database credentials and does not relax model sandbox isolation.

Search SQL is rendered as the isolated UID through a runner-owned helper outside the candidate. Its stdout file is capped by a process/descendant kernel file-size limit, including Python, direct descriptor and subprocess writes. After quiescence, bounded regular/no-follow readback copies at most 1 MiB to a runner-owned read-only lint input. The generated SQL and full-suite XML have separate fixed paths; regression reports are not reused.

Frontend disposable checks retain format/lint, tests and the real `build:check` TypeScript/Vite compile. Ordinary `build` still runs cloud release pre/post validators. Real required candidate PR CI remains the final independent gate; passing trusted checks never bypasses it. Record actual hosted fixture evidence for the implementation head before another paid attempt.

### Provider usage and the proposed temporary capacity ceiling

Provider usage and PawLocal reservations measure different things. The #329 numeric reports contain 27 inference requests, 799,764 input tokens and 9,679 output tokens; cached input and reasoning output are subsets, not extra tokens. Request budgeting reserved 3,402,000 output tokens, and admission separately reserved the full $76.176 two-role envelope. Neither lower actual usage nor a failed merge refunds these reservations or the consumed generation.

The previously activated capacity context was $300/40 runs. Issue #331 proposes a temporary **$400 monthly ceiling with 40 runs**, keeping 126,000 output tokens per call, 64 calls and the $76.176 envelope unchanged. At the recorded October ledger total of $278.7352, one further full envelope would total $354.9112. The proposed profile is not activated by source or documentation changes: activation requires reviewed merge and separate protected-profile readback. No consumed generation is retried or refunded.
