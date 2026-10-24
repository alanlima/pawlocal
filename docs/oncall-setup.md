# On-call responder setup guide

This guide covers every step required to activate the automated incident responder from scratch — whether you are deploying PawLocal yourself or have forked this repository. It describes the exact manual operations that cannot be automated, and the sequence in which to do them.

> [!IMPORTANT]
> Infrastructure provisioning and model spending require explicit owner approval at each stage. Do not provision AWS resources or enable the OpenAI API key until the corresponding authorisation step is complete.

## Architecture overview

The full incident loop is:

```
Grafana alert → Lambda Function URL → GitHub Actions (incident-responder.yml)
    → preflight / triage → Codex fixer → Codex reviewer → candidate PR
    → CI checks → trusted squash merge → development deployment
    → recovery verification → production promotion → production recovery
```

All components are disabled by default. Each section below enables one layer.

The two GitHub App identities are deliberately separate:

| App | Permissions | Used by |
|---|---|---|
| **Dispatch App** | Actions: Read & write | Lambda receiver — dispatches `incident-responder.yml` |
| **Publisher App** | Contents, Pull requests, Issues, Commit statuses: R/W; Administration: Read | Trusted workflow jobs — creates PR, posts status checks, squash-merges |

Model jobs (fixer, reviewer) hold neither App key, no AWS credentials and no write-capable GitHub token. The production promoter holds only `GITHUB_TOKEN` with Actions write.

---

## Prerequisites

Confirm each item is complete before continuing:

- [ ] AWS infrastructure provisioned in `development` and `production` Terraform states ([operator guide](terraform-greenfield-operations.md)).
- [ ] Grafana Cloud stack configured and DEV dashboards verified (Issue #59 / [hosted-telemetry-operations.md](hosted-telemetry-operations.md)).
- [ ] Repository branch ruleset `Protect Main Branch` is active and enforces squash-only merge, no force-push/deletion.
- [ ] GitHub Environments exist: `oncall-development`, `oncall-production`, `incident-change-authorization`, `ordinary-change-approval`.

---

## Step 1 — Create the Dispatch GitHub App

The Dispatch App allows the Lambda receiver to trigger `incident-responder.yml` on `main`. Fill in every field exactly as shown below.

### 1a. Register the App

Go to [github.com/settings/apps/new](https://github.com/settings/apps/new).

| Field | Value |
|---|---|
| **GitHub App name** | `pawlocal-incident-dispatcher` |
| **Description** | Dispatches the PawLocal automated incident-response workflow when a signed Grafana alert is received by the Lambda receiver. Holds only Actions write on the configured repository; no content, PR or merge authority. |
| **Homepage URL** | `https://pawlocal.alanlima.cloud` *(replace with your production domain)* |

### 1b. Webhook section

Uncheck **Active** under the **Webhook** section. Leave the Webhook URL field empty. The Dispatch App does not receive webhooks — it only calls the GitHub API to dispatch a workflow.

### 1c. Repository permissions

Expand **Repository permissions** and set:

| Permission | Level |
|---|---|
| **Actions** | Read and write |

Leave every other repository and account permission as **No access**.

### 1d. Where can this GitHub App be installed?

Select **Only on this account**. This prevents the App from being installed on other accounts.

### 1e. Create and note the App ID

Click **Create GitHub App**. On the App settings page that opens:

- Copy the **App ID** (shown near the top, e.g. `1234567`). You will use it in Step 5.

### 1f. Generate a private key

Scroll to the **Private keys** section and click **Generate a private key**. A `.pem` file downloads automatically. Store it securely — you will need it in Step 3.

> [!CAUTION]
> Never commit the `.pem` file to the repository. Treat it like a password.

### 1g. Install the App on your repository

1. In the left sidebar click **Install App**.
2. Click **Install** next to your account (`alanlima`).
3. Select **Only select repositories**, then choose `alanlima/pawlocal`.
4. Click **Install**.
5. After installing, look at the browser URL bar. It will read something like `github.com/settings/installations/12345678`. The number at the end is the **Installation ID**. Copy it.

You now have three values needed later:
- App ID (from 1e)
- Installation ID (from 1g)
- Private key `.pem` file (from 1f)

---

## Step 2 — Create the Publisher GitHub App

The Publisher App is used exclusively by trusted workflow jobs to create the incident PR, post commit status checks, and perform the squash merge. It never executes candidate code or holds deployment credentials.

### 2a. Register the App

Go to [github.com/settings/apps/new](https://github.com/settings/apps/new).

| Field | Value |
|---|---|
| **GitHub App name** | `pawlocal-incident-publisher` |
| **Description** | Creates and merges PawLocal automated incident-fix pull requests after independent machine review. Holds content, PR, issue and status-check write access plus Administration read (to verify branch protection rules). No deployment or infrastructure authority. |
| **Homepage URL** | `https://pawlocal.alanlima.cloud` *(replace with your production domain)* |

### 2b. Webhook section

Uncheck **Active** under the **Webhook** section. Leave the Webhook URL field empty.

### 2c. Repository permissions

Expand **Repository permissions** and set:

| Permission | Level |
|---|---|
| **Administration** | Read-only |
| **Commit statuses** | Read and write |
| **Contents** | Read and write |
| **Issues** | Read and write |
| **Pull requests** | Read and write |

Leave every other permission as **No access**.

> [!NOTE]
> **Administration read-only** is required so trusted preflight and publisher jobs can read the active branch ruleset and verify that no human-bypass actors or unexpected protections exist before creating or merging a PR. Administration **write** is explicitly not granted.

### 2d. Where can this GitHub App be installed?

Select **Only on this account**.

### 2e. Create and note the App ID

Click **Create GitHub App** and copy the **App ID** from the settings page.

### 2f. Generate a private key

Scroll to **Private keys** and click **Generate a private key**. Save the downloaded `.pem` file securely.

### 2g. Install the App on your repository

1. Click **Install App** in the left sidebar.
2. Click **Install** next to your account.
3. Select **Only select repositories** → `alanlima/pawlocal`.
4. Click **Install**.
5. Note the **Installation ID** from the URL bar.

You now have three values:
- App ID (from 2e)
- Installation ID (from 2g)
- Private key `.pem` file (from 2f)

---

## Step 3 — Populate AWS SSM secrets

Four AWS Systems Manager SecureString parameters must be created. Use the AWS CLI or console with the IAM identity that has SSM write permission.

Replace `<project>` with your project name (default: `pawlocal`) and `<env>` with `development` or `production`.

```bash
# Grafana alerting HMAC secret — at least 32 random bytes
openssl rand -hex 32 | aws ssm put-parameter \
  --name "/pawlocal/<env>/secrets/grafana/webhook-hmac" \
  --type SecureString \
  --value "$(cat)" \
  --overwrite

# Dispatch App RSA private key (from Step 1)
aws ssm put-parameter \
  --name "/pawlocal/<env>/secrets/oncall/dispatch-app-private-key" \
  --type SecureString \
  --value "$(cat /path/to/dispatcher-private-key.pem)" \
  --overwrite
```

Run the above for **both** `development` and `production`. Do not store private key content in shell history; use a pipe from a file or a secrets manager.

> [!CAUTION]
> Never commit PEM files or hex secrets to the repository. Never store them in Terraform state. AWS SSM SecureString is the only authorised storage.

Verify the parameters exist (no decrypted value read-back):
```bash
aws ssm describe-parameters --filters "Key=Name,Option=Contains,Values=/pawlocal/"
```

---

## Step 4 — Configure GitHub Environments

### 4a. `oncall-development` environment

Navigate to **Repository → Settings → Environments → oncall-development**.

Add the following **Secrets**:

| Secret name | Value |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key (`sk-...`) from a dedicated API project. |
| `PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY` | Contents of the Publisher App `.pem` file (Step 2). |

Add the following **Variables**:

| Variable name | Value |
|---|---|
| `PAWLOCAL_ONCALL_PUBLISHER_APP_ID` | Publisher App ID (Step 2). |
| `PAWLOCAL_ONCALL_PUBLISHER_INSTALLATION_ID` | Publisher App Installation ID (Step 2). |
| `PAWLOCAL_ONCALL_QUOTA_ISSUE` | Number of the Quota & Emergency Stop Ledger issue (e.g. `269`). |
| `PAWLOCAL_ONCALL_ENABLED` | `false` — leave disabled until the full loop is demonstrated. |
| `PAWLOCAL_ONCALL_DISPATCH_ACTOR` | Exact GitHub login of the Dispatch App bot (format: `<app-slug>[bot]`). |
| `PAWLOCAL_GRAFANA_URL` | Your Grafana stack base URL (e.g. `https://alanlima.grafana.net`). |
| `PAWLOCAL_ONCALL_MODEL_PROFILE` | Leave **unset** until the owner approves a model, rate, and quota profile. |

Add the following **Secret**:

| Secret name | Value |
|---|---|
| `PAWLOCAL_GRAFANA_QUERY_TOKEN` | Grafana Stack API token with Viewer scope, for telemetry reads during triage. |

### 4b. `oncall-production` environment

Mirror the setup above for `oncall-production`, except:

- `OPENAI_API_KEY` is configured in this environment too (used by the production recovery phase).
- `PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED` must remain **unset** until G2 (DEV demonstration) passes.

### 4c. `incident-change-authorization` environment

This environment is used by the publisher job to cryptographically verify incident lineage before creating a PR or merging.

Add:

| Secret | Value |
|---|---|
| `PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY` | Same Publisher App `.pem` as above. |

Add:

| Variable | Value |
|---|---|
| `PAWLOCAL_ONCALL_PUBLISHER_APP_ID` | Publisher App ID. |
| `PAWLOCAL_ONCALL_PUBLISHER_INSTALLATION_ID` | Publisher App Installation ID. |

### 4d. `ordinary-change-approval` environment

Add yourself (or the team lead) as a required **Reviewer** so that ordinary (non-incident) PRs require human approval before the `PawLocal change authorization` status check can pass.

> [!NOTE]
> This is the gate that preserves human oversight for all non-automated changes. Incident PRs bypass it only through cryptographic lineage verification — not by removing it.

---

## Step 5 — Update the Dispatch App config in Terraform / Lambda

The Lambda receiver is deployed with placeholder App IDs. Update the `oncall_receiver` object in your Terraform plan environment variable (`PAWLOCAL_ONCALL_RECEIVER_CONFIG`) with the real values from Step 1:

```json
{
  "app_id": "<Dispatch App ID>",
  "installation_id": "<Dispatch Installation ID>",
  "repository_id": "<numeric GitHub repository ID>",
  "repository": "<org>/<repo>",
  "allowed_services": ["pawlocal-api"],
  "allowed_alerts": ["pawlocal-development-search-detail-failure"]
}
```

Then update the SSM private key populated in Step 3 with the real Dispatch App private key.

> [!TIP]
> Find the numeric repository ID with:
> ```bash
> gh api /repos/<org>/<repo> --jq .id
> ```

---

## Step 6 — Update the branch ruleset

Navigate to **Repository → Settings → Rules → Rulesets → Protect Main Branch** and:

1. Set **Require a review from Code Owners** to **disabled** (code-owner review is now replaced by machine authorization).
2. Under **Required status checks**, add `PawLocal change authorization` and pin it to the **Publisher App ID** as the expected status source.
3. Verify that squash merge, no-force-push, and no-deletion protections remain enabled.

> [!IMPORTANT]
> Do not disable Code Owners until the `PawLocal change authorization` status check is pinned to the correct Publisher App ID and independently verified. Removing Code Owners before the replacement gate is active removes all merge protection.

---

## Step 7 — Create the Quota & Emergency Stop Ledger issue

The responder reads this issue before each model call. Closing it immediately halts all ongoing and new incident runs.

Create an issue in your repository with the **exact marker** in the body:

```markdown
<!-- pawlocal-oncall-quota:v1 -->
# PawLocal On-Call Quota & Emergency Stop Ledger

This issue is the tamper-evident quota ledger and owner-controlled emergency stop mechanism.

- **Global Stop Control**: Closing this issue immediately denies admission and halts active responder jobs.
- **Ledger Entries**: Each run appends a signed reservation comment before model execution.
```

Set `PAWLOCAL_ONCALL_QUOTA_ISSUE` in both `oncall-development` and `oncall-production` to this issue number.

---

## Step 8 — Approve and configure the model profile

The `quota.py` admission gate enforces a fully populated, owner-approved JSON profile before any model call is made. The profile must name a real model, carry current pricing from an official source, and specify hard numeric ceilings that fit within the gateway's enforced limits.

### Recommended model: `o4-mini`

**`o4-mini` is the recommended choice** for the fixer and reviewer roles for these reasons:

| Property | Detail |
|---|---|
| **Capability** | Native reasoning model — plans multi-step repairs, writes tests, and explains confidence. Designed for code-heavy, logic-intensive tasks. |
| **Speed** | Significantly faster than `o1` or `o3` at the same quality tier. The 20-minute admission-to-PR deadline is tight; o4-mini consistently finishes within it. |
| **Cost** | \$1.10 / M input tokens, \$4.40 / M output tokens (Standard tier, October 2026). Roughly 4× cheaper than GPT-4o per token while outperforming it on code tasks. |
| **`codex-action` compatibility** | Explicitly supported by `codex-action` v0.163.0 (the pinned version in `incident-responder.yml`) via the Responses API. |
| **Effort knob** | Supports `low` / `medium` / `high` reasoning effort, letting you tune speed vs. quality within the same model. |

> **Pricing source (verify before approving):** `https://platform.openai.com/docs/pricing`

#### Why not GPT-4o?

GPT-4o costs \$2.50 / M input and \$10.00 / M output — roughly 2.3× more expensive per token with no reasoning advantage for structured code repairs. Reserve GPT-4o for cases requiring multimodal input, which the incident responder does not use.

#### Why not o3 or o1?

Both are slower and more expensive than o4-mini for this class of task. The 20-minute hard deadline makes latency a first-class constraint.

---

### Choosing the effort level

| Effort | Use when |
|---|---|
| `low` | The alert class is simple and well-scoped (e.g., a single missing index). Fastest, cheapest. |
| `medium` | **Recommended starting point.** Handles most search/detail API repairs without burning through the token budget. |
| `high` | Reserve for alerts the `medium` run consistently fails to diagnose. Approve a new profile with higher token ceilings before enabling. |

**Start with `medium`.**

---

### Hard limits enforced by `quota.py`

The gateway validates these fields against hard coded bounds. Your profile values must satisfy all of them:

| Field | Gateway maximum | Recommended value |
|---|---|---|
| `requests_per_role` | 32 | `4` |
| `input_per_request` | 250 000 tokens | `100000` |
| `output_per_request` | 32 000 tokens | `16000` |
| `input_per_role` | ≤ `input_per_request × requests_per_role` | `200000` |
| `output_per_role` | ≤ `output_per_request × requests_per_role` | `32000` |
| `promotion_seconds` | 3 600 s (1 h) | `3600` |
| `recovery_seconds` | 600–900 s | `720` |
| `monthly_runs` | 1 000 | `20` |

---

### Cost estimate

With the recommended values and `o4-mini` pricing:

| Item | Calculation | Cost |
|---|---|---|
| Input per role (2 roles) | 200 000 tokens × 2 × \$1.10 / M | **\$0.44** |
| Output per role (2 roles) | 32 000 tokens × 2 × \$4.40 / M | **\$0.28** |
| **Per incident (worst-case)** | | **≈ \$0.72** |
| **Monthly ceiling (20 runs)** | \$0.72 × 20 | **≈ \$14.40** |

Setting `monthly_microdollars` to `20000000` (\$20.00) gives comfortable headroom over the 20-run worst case while keeping a hard stop well below \$30.

> [!NOTE]
> `quota.py` charges the **full worst-case envelope** before forwarding — not actual usage. Failed, cancelled, or interrupted jobs remain charged. There is no automatic refund. The \$20 monthly ceiling is the outer bound, not an expected bill.

---

---

### How to get the Grafana Alert Rule UIDs (`rule_uids`)

In PawLocal, `rule_uids` identifies the synthetic search-to-detail journey alert rule for each environment that the incident responder observes during recovery.

#### Option A: Use the canonical repository defaults (Recommended)
If you provision alert rules using the repository tools (`observability/grafana/cloud/experience.py`), the predefined UIDs are:

| Environment | Canonical Rule UID |
|---|---|
| **Development** | `pawlocal-development-search-detail` |
| **Production** | `pawlocal-production-search-detail` |

#### Option B: Find the Rule UID in Grafana Cloud UI
If you create alert rules manually or customize their names:
1. Log in to your Grafana Cloud stack (e.g. `https://<stack>.grafana.net`).
2. In the left navigation, go to **Alerts & IRM** (or **Alerting**) → **Alert rules**.
3. Expand folder **`pawlocal-development`** or **`pawlocal-production`**.
4. Click on your search-detail journey failure alert rule.
5. In your browser URL bar, copy the identifier after `/alerting/`:
   ```
   https://<stack>.grafana.net/alerting/<RULE_UID>/view
   ```
   *(The UID is also displayed under the rule details section as **Rule UID**).*

---

### Generating the Profile JSON

You can generate the complete, validated JSON string using the repository helper script without manual JSON formatting or timestamp math:

```bash
python ops/incident-response/generate-profile.py
```

This helper:
- Uses the recommended `o4-mini` model, `medium` effort, and \$20.00 monthly budget ceiling.
- Automatically sets the canonical rule UIDs (`pawlocal-development-search-detail` and `pawlocal-production-search-detail`). (Pass `--dev-rule-uid <uid>` and `--prod-rule-uid <uid>` if you use custom UIDs).
- Automatically calculates the current UTC month (`approved_month`), UTC review timestamp (`rates_reviewed_at`), and 30-day expiration timestamp (`expires_at`).
- Runs the output through `quota.py` validation to guarantee it passes the gateway checks.

**Example output ready to paste into `PAWLOCAL_ONCALL_MODEL_PROFILE`:**

```json
{"model":"o4-mini","effort":"medium","service_tier":"default","input_rate":1100000,"output_rate":4400000,"monthly_microdollars":20000000,"monthly_runs":20,"promotion_seconds":3600,"recovery_seconds":720,"rule_uids":{"development":"pawlocal-development-search-detail","production":"pawlocal-production-search-detail"},"requests_per_role":4,"input_per_request":100000,"output_per_request":16000,"input_per_role":200000,"output_per_role":32000,"approval":"alanlima/pawlocal/issues/269","approved_month":"2026-10","rates_source":"https://platform.openai.com/docs/pricing","rates_reviewed_at":"2026-10-24T03:04:03Z","expires_at":"2026-11-23T03:04:03Z"}
```

---

### Manual Profile JSON Reference

If you prefer to construct the JSON manually, satisfy all fields below:

```json
{
  "model": "o4-mini",
  "effort": "medium",
  "service_tier": "default",
  "input_rate": 1100000,
  "output_rate": 4400000,
  "monthly_microdollars": 20000000,
  "monthly_runs": 20,
  "promotion_seconds": 3600,
  "recovery_seconds": 720,
  "rule_uids": {
    "development": "pawlocal-development-search-detail",
    "production":  "pawlocal-production-search-detail"
  },
  "requests_per_role": 4,
  "input_per_request": 100000,
  "output_per_request": 16000,
  "input_per_role": 200000,
  "output_per_role": 32000,
  "approval": "alanlima/pawlocal/issues/269",
  "approved_month": "<YYYY-MM of current month, e.g. 2026-10>",
  "rates_source": "https://platform.openai.com/docs/pricing",
  "rates_reviewed_at": "<UTC timestamp when you reviewed pricing, e.g. 2026-10-24T03:00:00Z>",
  "expires_at": "<UTC timestamp at most 31 days from rates_reviewed_at>"
}
```

**Before enabling:**

1. Visit `https://platform.openai.com/docs/pricing` and confirm `o4-mini` input/output rates match `1100000` / `4400000` microdollars per million tokens.
2. Record the pricing review date in `rates_reviewed_at`.
3. Set `approved_month` to the current UTC month (`YYYY-MM`).
4. Set `expires_at` to no more than 31 days from now (the gateway rejects profiles older than 31 days).
5. Ensure `rule_uids` match your Grafana alert rule UIDs.
6. Record approval on the Quota Ledger issue (#269) before pasting the profile into the GitHub Environment variable.

> [!IMPORTANT]
> The profile **must be re-issued each calendar month** — `approved_month` must match the current UTC month or the gateway denies admission. Budget a quick monthly run of `python ops/incident-response/generate-profile.py` to refresh the variable.

---

## Step 9 — Create the Grafana alerting contact point (DEV)

In Grafana Cloud, navigate to:
**Alerts & IRM** → **Alerting** → **Notification configuration** → **Contact points** tab (first tab) → **+ Add contact point**.

| Field | Value |
|---|---|
| **Name** | `pawlocal-development-oncall` |
| **Integration** | `Webhook` |
| **URL** | Value of SSM parameter `/pawlocal/development/config/oncall/webhook-url` (your DEV Lambda Function URL) |
| **HTTP Method** | `POST` |

Under **Optional Webhook settings**, expand **HMAC setup**:
1. Check **Enable HMAC setup**.
2. **Secret**: Decrypted value of SSM parameter `/pawlocal/development/secrets/grafana/webhook-hmac` (32-byte hex string).
3. **Header**: `X-Grafana-Alerting-Signature`
4. **Timestamp header**: `X-Grafana-Alerting-Timestamp`

Click **Save contact point**.

> [!NOTE]
> Keep this contact point **unassigned** to any notification policy rule until Step 11. Do not route live alerts to it until after the controlled manual test in Step 10 succeeds.
>
> *(Why not Terraform? In PawLocal, the contact point is created via the Grafana UI because Terraform state must never store runtime secret payloads such as the HMAC secret, and Grafana Cloud uses a single shared notification policy tree across both DEV and PROD).*

---

## Step 10 — Enable the responder and run a controlled test

1. Set `PAWLOCAL_ONCALL_ENABLED = true` in `oncall-development`.
2. Set `PAWLOCAL_ONCALL_MODEL_PROFILE` to the owner-approved profile JSON.
3. Manually POST a signed test payload to the DEV Function URL to verify the full dispatch path:

```bash
# Read the HMAC secret
SECRET=$(aws ssm get-parameter \
  --name "/pawlocal/development/secrets/grafana/webhook-hmac" \
  --with-decryption --query Parameter.Value --output text)

BODY='{"receiver":"pawlocal-development-oncall","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"pawlocal-development-search-detail-failure","environment":"development","service":"pawlocal-api"},"startsAt":"2026-10-24T00:00:00Z","endsAt":"0001-01-01T00:00:00Z","fingerprint":"0123456789abcdef01234567"}]}'

TS=$(date +%s)
SIG=$(printf '%s:%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -s -X POST "<DEV_FUNCTION_URL>" \
  -H "Content-Type: application/json" \
  -H "x-grafana-alerting-timestamp: $TS" \
  -H "x-grafana-alerting-signature: $SIG" \
  -d "$BODY"
```

Expected response: `204 No Content` (GitHub accepted dispatch) or `502` if the App credentials in SSM/Lambda config are not yet correct.

4. Watch [GitHub Actions](https://github.com/<org>/<repo>/actions/workflows/incident-responder.yml) for the dispatched run.
5. Verify the full loop: preflight claim → fixer → checks → reviewer → candidate PR → CI → squash merge → development deployment → recovery verification.
6. This is the **G2 gate** (development incident demonstration acceptance).

---

## Step 11 — Activate the Grafana contact point (DEV)

Once the controlled test in Step 10 passes (G2):

1. Go to **Alerts & IRM** → **Alerting** → **Notification configuration** → **Notification policies** tab.
2. Under your notification routing tree, add a nested policy (or edit the policy for development):
   - **Matching labels**: `environment = development`, `service = pawlocal-api`
   - **Contact point**: `pawlocal-development-oncall`
   - Click **Save policy**.
3. Verify deduplication: firing the alert twice within the settling window triggers only one workflow run due to the preflight incident issue claim.
4. Verify a resolution event closes the incident issue cleanly.

---

## Step 12 — Enable production-origin incidents

After G2 is accepted:

1. Set `PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED = true` in `oncall-production`.
2. Configure a PROD Grafana contact point targeting the PROD Function URL with the PROD HMAC secret.
3. Assign it to a notification policy matching `environment=production` alerts.
4. Verify a live PROD alert triggers remediation and results in the exact DEV-verified release being automatically promoted to production with no runtime human approval gate.

---

## Emergency stop and secret rotation

### Stop the responder immediately

Close [the Quota & Emergency Stop Ledger issue](https://github.com/<org>/<repo>/issues/<issue-number>). Trusted code reads it before every model request, mutation and observation step. Running jobs will finish their current step and escalate; no new mutation begins.

For running model work, also cancel the active workflow run in GitHub Actions.

### Rotate the Grafana HMAC secret

```bash
# Generate new secret
NEW_SECRET=$(openssl rand -hex 32)

# Update SSM (do this BEFORE updating Grafana)
aws ssm put-parameter \
  --name "/pawlocal/<env>/secrets/grafana/webhook-hmac" \
  --type SecureString \
  --value "$NEW_SECRET" \
  --overwrite

# Update the Grafana contact point HMAC signing key in the UI
# Test that new signed payloads succeed before discarding the old secret
```

The Lambda re-reads the SSM parameter on every request, so there is no cache to flush.

### Rotate the Dispatch App private key

1. Generate a new private key in the GitHub App settings.
2. Update the SSM parameter for **both** environments.
3. Test that a signed alert reaches GitHub (expected: 502 if App is otherwise correctly configured; 401 means the key is wrong).
4. Delete the old private key from the GitHub App settings.

### Rotate the Publisher App private key

1. Generate a new private key in the GitHub App settings.
2. Update `PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY` in all affected GitHub Environments (`oncall-development`, `oncall-production`, `incident-change-authorization`).
3. Trigger a test workflow run to confirm the new key mints a valid token.
4. Delete the old key.

---

## Verification checklist before going live

| Check | How to verify |
|---|---|
| Unsigned POST → 401 | `curl -X POST <function-url> -H "Content-Type: application/json" -d '{}'` |
| Unauthorized service → 403 | Signed POST with service not in `allowed_services` |
| Valid alert → 204 (or 502 if App config pending) | Signed POST with correct alert shape |
| Missing `OPENAI_API_KEY` → workflow fails closed | Remove the secret, dispatch a test, confirm job exits without calling OpenAI |
| Ledger issue closed → admission denied | Close the quota issue, send a valid alert, confirm the workflow exits at preflight |
| Ordinary PR still requires human approval | Open a normal PR and confirm `ordinary-change-approval` gate requires a reviewer |
| DEV dashboards show 0 PROD data | Run dashboard test: `terraform test -filter=dashboards.tftest.hcl` |

---

## Related documentation

- [Incident responder specification](specs/incident-responder.md)
- [Hosted telemetry operations](hosted-telemetry-operations.md)
- [Signed Lambda receiver README](../ops/incident-response/README.md)
- [Trusted workflow README](../ops/incident-response/ACTIONS.md)
- [GitHub Actions workflow reference](github-actions.md)
- [Terraform operator guide](terraform-greenfield-operations.md)
- [Configuration inventory](configuration-inventory.md)
- [Monitoring and incident response wiki](https://github.com/alanlima/pawlocal/wiki/Monitoring-and-incident-response)
