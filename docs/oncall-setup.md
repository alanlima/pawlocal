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

The Dispatch App allows the Lambda receiver to trigger `incident-responder.yml` on `main`.

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Set **App name** (e.g. `pawlocal-incident-dispatcher`).
3. Set **Homepage URL** to your deployment URL (e.g. `https://pawlocal.example.com`).
4. Uncheck **Webhook → Active** (no webhooks needed).
5. Under **Repository permissions**, set **Actions → Read and write**.
6. Click **Create GitHub App** and note the **App ID** shown on the app's settings page.
7. Scroll to **Private keys** and click **Generate a private key**. Save the downloaded `.pem` file securely.
8. Click **Install App** (left sidebar), click **Install** under your account, choose **Only select repositories**, and pick `<your-org>/<your-repo>`.
9. After installing, note the **Installation ID** from the URL bar (the number at the end of `github.com/settings/installations/<id>`).

---

## Step 2 — Create the Publisher GitHub App

The Publisher App allows trusted workflow jobs to create PRs, post status checks, and squash-merge incident fixes.

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Set **App name** (e.g. `pawlocal-incident-publisher`).
3. Set **Homepage URL** to your deployment URL.
4. Uncheck **Webhook → Active**.
5. Under **Repository permissions**, set:
   - **Contents → Read and write**
   - **Pull requests → Read and write**
   - **Issues → Read and write**
   - **Commit statuses → Read and write**
   - **Administration → Read-only**
6. Click **Create GitHub App** and note the **App ID**.
7. Generate a **Private key** and save the `.pem` file.
8. Install the app on your repository (same steps as the Dispatch App). Note the **Installation ID**.

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

Model admission is blocked until the owner explicitly sets a profile. The profile must specify a real approved model name, current rates (in microdollars per million tokens), monthly run and spending ceilings, per-request token limits, and approved provenance timestamps.

**Do not set `PAWLOCAL_ONCALL_MODEL_PROFILE` until you have:**
- Confirmed the model pricing at the [OpenAI API pricing page](https://openai.com/api/pricing/).
- Agreed a monthly spending ceiling.
- Created a dedicated OpenAI API project and billing budget alert.
- Recorded the approval reference in the quota ledger issue.

The profile JSON schema is enforced by `ops/incident-response/quota.py`. Fixture values in tests are not live approval.

---

## Step 9 — Enable Grafana alerting contact point

Configure a Grafana alerting contact point of type **Webhook** targeting the Lambda Function URL for your environment:

- **DEV contact point URL**: value of SSM parameter `/pawlocal/development/config/oncall/webhook-url`
- **HMAC signing secret**: value of SSM parameter `/pawlocal/development/secrets/grafana/webhook-hmac`

In the Grafana alerting contact point settings, enable:
- **HTTP Method**: POST
- **Authentication**: Custom header `X-Grafana-Alerting-Signature` and `X-Grafana-Alerting-Timestamp` (Grafana sets these automatically when an HMAC secret is configured).

Keep the contact point **disabled or unassigned** to any notification policy until Step 11.

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

Once G2 passes:

1. Assign the DEV contact point to a notification policy that matches `environment=development` alerts.
2. Verify deduplication (posting the same alert twice within the window produces only one workflow run due to the incident issue claim).
3. Verify a resolution event closes the incident cleanly.

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
