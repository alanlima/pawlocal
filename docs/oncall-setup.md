# On-call responder setup guide

This guide covers every step required to activate the automated incident responder from scratch for canonical deployments of this repository (`alanlima/pawlocal`). It describes the exact manual operations that cannot be automated, and the sequence in which to do them.

> [!NOTE]
> Running the responder on a forked repository requires adapting pinned repository and owner identities in trusted incident code (`publisher-token.mjs`, `admission.py`, `protection.py`, `control.py`). This multi-repository enhancement is tracked in backlog issue #275.

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
>
> **Why these secrets are provisioned directly in SSM instead of Terraform:**
> Under project rules (`AGENTS.md`), runtime secret payloads must never be stored in Terraform state or committed to source control. Terraform provisions the Lambda role and IAM policies granting `ssm:GetParameter` access to these exact parameter ARNs, while the secret payloads themselves must be provisioned directly in SSM SecureString. A separately automated secret lifecycle remains tracked in the project backlog.

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
- `PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED` must remain **unset** until G2 (DEV demonstration) passes, unless demonstrating the full end-to-end promotion loop.

> [!NOTE]
> Under the full autonomous loop design (DEC-012 / `ops/incident-response/ACTIONS.md`), `promotion.main()` and `bindings_ready()` require approved bindings for both environments in `bindings.json`. When running a development incident test, if `PAWLOCAL_ONCALL_ENABLED` or `PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED` remains disabled in `oncall-production`, the workflow verifies recovery in development and then cleanly stops at the production promotion step. To demonstrate the complete loop through production recovery, configure and approve both environments.

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

Navigate to **Repository → Settings → Environments → ordinary-change-approval**.

This environment gates ordinary (non-incident) pull requests. Under the repository ruleset, `main` requires the `PawLocal change authorization` commit status check. For ordinary PRs raised by developers, GitHub Actions enters this environment and pauses for your approval before minting the status token and marking the check as `success`.

1. **Environment protection rules**:
   - Add yourself (or the repository owner) under **Required reviewers**.
   - Leave **Wait timer** disabled.

2. **Secrets**:

   | Secret name | Value |
   |---|---|
   | `PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY` | Same Publisher App `.pem` as above. |

3. **Variables**:

   | Variable name | Value |
   |---|---|
   | `PAWLOCAL_ONCALL_PUBLISHER_APP_ID` | Publisher App ID. |
   | `PAWLOCAL_ONCALL_PUBLISHER_INSTALLATION_ID` | Publisher App Installation ID. |

> [!NOTE]
> **How ordinary PR approval works:**
> When an ordinary PR is opened or synchronized, `.github/workflows/change-authorization.yml` classifies it as `route: ordinary` and starts the `ordinary-approval` job.
> 1. The job pauses with a pending status waiting for deployment approval in `ordinary-change-approval`.
> 2. You go to the GitHub Actions run and click **Review deployments → Approve and deploy**.
> 3. The job resumes, mints a status token via the Publisher App, verifies that the PR head SHA hasn't changed, and posts `success` to the `PawLocal change authorization` status check.
> 4. Once this check passes, GitHub allows the PR to be squash-merged into `main`.

### 4e. Runtime environment protection rules and branch policies

The automated incident responder includes a strict preflight check (`admission.readiness()` calling `settings.runtime_ready()`) that validates all 8 runtime deployment environments via the GitHub API before admitting any automated incident run:
- `development`
- `development-plan`
- `development-apply`
- `production`
- `production-plan`
- `production-apply`
- `oncall-development`
- `oncall-production`

Configure **each** of these 8 environments with the following settings:

1. **Deployment branches**:
   - Select **Selected branches**.
   - Add rule: `main` (only the `main` branch is permitted).
2. **Environment protection rules**:
   - **Required reviewers**: Ensure **no reviewers** are configured (remove any existing reviewers).
   - **Wait timer**: Ensure **no wait timer** is configured (0 minutes).

> [!IMPORTANT]
> **Why reviewers are removed from runtime environments:**
> Under the unattended incident recovery model (Issue #239), emergency fixes deploy from `main` to development and production automatically without interactive human approvals in the deployment pipeline.
> Human oversight for human changes is preserved by the change authorization workflow at **PR merge time** (`ordinary-change-approval`), rather than inside the downstream deployment environments.
> Separately gated workflows—such as account bootstrap (`iam-bootstrap-apply`), environment setup, and infrastructure teardown (`destroy`)—retain their existing manual approval gates and are not part of this runtime environment group.

---

## Step 5 — Update the Dispatch App config and apply via Terraform

The Lambda receiver is initially provisioned with placeholder App IDs (`100001`/`200001`). To apply the real Dispatch App credentials to the live Lambda without any manual CLI mutations:

### 5a. Update `PAWLOCAL_ONCALL_RECEIVER_CONFIG` variable
In **Settings → Environments → development-plan**, update (or add) the variable `PAWLOCAL_ONCALL_RECEIVER_CONFIG` with your real Dispatch App details from Step 1:

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

> [!TIP]
> Find your numeric repository ID using GitHub CLI:
> ```bash
> gh api /repos/<org>/<repo> --jq .id
> ```

### 5b. Trigger the Terraform workflow to apply changes to AWS
Once the environment variable is saved, run the Terraform environment workflow so Terraform plans and applies the new configuration to the Lambda receiver:

1. In GitHub, go to **Actions** → **Terraform environment plan and apply** (`terraform-environment.yml`).
2. Click **Run workflow**:
   - **Environment**: `development`
   - **Phase**: `converge`
   - **Backend image**: Paste the current deployed backend image tag.
     *(Find it quickly via CLI: `gh api /repos/<org>/<repo>/deployments?environment=development --jq ".[0].payload.backend_image"`)*
3. Click **Run workflow**.
4. The **Plan** step will show only the Lambda environment variables changing from the placeholders (`100001`/`200001`) to your real Dispatch App ID and Installation ID.
5. Approve the deployment in `development-apply` (if required) and allow the apply job to complete successfully.

---

## Step 6 — Update the branch ruleset

The automated incident responder verifies the repository ruleset during preflight (`admission.readiness()`). It requires strict status checks, the three required candidate checks, and no bypass actors (`current_user_can_bypass == "never"`). Note that GitHub's REST API omits `bypass_actors` from GET responses for tokens with read-only administration permissions; preflight accepts omitted `bypass_actors` while strictly confirming `current_user_can_bypass == "never"`, relying on the owner's initial setup below to configure and verify `bypass_actors: []`.

### Option A — Automated via GitHub CLI (Recommended)

Run the following command using the GitHub CLI (`gh`) and your Publisher App ID from Step 2.

**Bash (Linux / macOS):**
```bash
PUBLISHER_APP_ID="<your-publisher-app-id>"

RULESET_ID=$(gh api repos/:owner/:repo/rulesets --jq '.[] | select(.name=="Protect Main Branch") | .id')

cat <<EOF | gh api -X PUT "repos/:owner/:repo/rulesets/$RULESET_ID" -H "Accept: application/vnd.github+json" --input -
{
  "name": "Protect Main Branch",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": [
        "~DEFAULT_BRANCH"
      ],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "deletion"
    },
    {
      "type": "non_fast_forward"
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "required_reviewers": [],
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "require_extra_approval_for_unattributed_changes": true,
        "allowed_merge_methods": [
          "squash"
        ]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          {
            "context": "PawLocal change authorization",
            "integration_id": $PUBLISHER_APP_ID
          },
          {
            "context": "Backend checks / Backend checks"
          },
          {
            "context": "Frontend checks and HTTP-mode build / frontend"
          }
        ]
      }
    }
  ],
  "bypass_actors": []
}
EOF
```

**PowerShell (Windows):**
```powershell
$PublisherAppId = <your-publisher-app-id>

$RulesetId = (gh api repos/:owner/:repo/rulesets | ConvertFrom-Json | Where-Object { $_.name -eq "Protect Main Branch" }).id

$Payload = @{
    name = "Protect Main Branch"
    target = "branch"
    enforcement = "active"
    conditions = @{ ref_name = @{ include = @("~DEFAULT_BRANCH"); exclude = @() } }
    rules = @(
        @{ type = "deletion" },
        @{ type = "non_fast_forward" },
        @{
            type = "pull_request"
            parameters = @{
                required_approving_review_count = 0
                dismiss_stale_reviews_on_push = $false
                required_reviewers = @()
                require_code_owner_review = $false
                require_last_push_approval = $false
                required_review_thread_resolution = $true
                require_extra_approval_for_unattributed_changes = $true
                allowed_merge_methods = @("squash")
            }
        },
        @{
            type = "required_status_checks"
            parameters = @{
                strict_required_status_checks_policy = $true
                do_not_enforce_on_create = $false
                required_status_checks = @(
                    @{ context = "PawLocal change authorization"; integration_id = [int]$PublisherAppId },
                    @{ context = "Backend checks / Backend checks" },
                    @{ context = "Frontend checks and HTTP-mode build / frontend" }
                )
            }
        }
    )
    bypass_actors = @()
} | ConvertTo-Json -Depth 10

$Payload | gh api -X PUT "repos/:owner/:repo/rulesets/$RulesetId" --input -
```

This automatically configures the active `Protect Main Branch` ruleset to:
- Pin `PawLocal change authorization` to your Publisher App ID.
- Include candidate checks `Backend checks / Backend checks` and `Frontend checks and HTTP-mode build / frontend`.
- Enable strict status check policy (`strict_required_status_checks_policy: true`).
- Enforce squash-only merging, no force-push, no deletion, and no bypass actors.

### Option B — Manual configuration via GitHub Web UI

> [!CAUTION]
> Under project rules (`AGENTS.md` line 314), never reduce required approvals or disable Code Owner review before the replacement `PawLocal change authorization` status check (pinned to the verified Publisher App ID) is added and verified. Disabling human reviews before machine authorization is active leaves the target branch unprotected against unreviewed changes.

Navigate to **Repository → Settings → Rules → Rulesets → Protect Main Branch**:

1. Under **Require status checks to pass** (configure and verify this FIRST):
   - Check **Require branches to be up to date before merging** (strict policy).
   - Add check: `PawLocal change authorization` (select your Publisher App as the status source so it is pinned to your Publisher App ID).
   - Add check: `Backend checks / Backend checks`.
   - Add check: `Frontend checks and HTTP-mode build / frontend`.
   - Independently verify that `PawLocal change authorization` is saved and pinned to the Publisher App before proceeding.
2. Under **Rules**:
   - Ensure **Restrict deletions** is checked.
   - Ensure **Block force pushes** is checked.
3. Under **Require a pull request before merging** (only after step 1 is verified):
   - **Required approvals**: `0` (machine authorization replaces human review gate).
   - **Dismiss stale pull request approvals when new commits are pushed**: Unchecked.
   - **Require review from Code Owners**: Unchecked (disabled).
   - **Require approval of the most recent push**: Unchecked.
   - **Require conversation resolution before merging**: Checked.
   - **Allowed merge methods**: Only **Squash merge**.
4. Under **Bypass list**:
   - Ensure no bypass actors are added (leave completely empty).

> [!IMPORTANT]
> `admission.readiness()` validates that all three status checks exist, that strict checks are enabled, and that no bypass actors exist. If any of these differ, preflight fails closed before any incident model is admitted.

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

The `quota.py` admission gate enforces a fully populated, owner-approved JSON profile before any model call is made. The profile must name a real model, carry current pricing from an official source, and specify hard numeric token/request/run ceilings that fit within the gateway's enforced limits. Monthly spending requires an explicit positive integer ceiling or the owner-approved unlimited mode below.

### Explicit unlimited monthly spending

Under [DEC-016 / #351](decisions.md#dec-016--temporary-unlimited-monthly-incident-spending-351), JSON `"monthly_microdollars": null` disables only the monthly dollar ceiling. Omission, strings such as `"unlimited"`, booleans, zero and negative values are invalid. Positive integer microdollars retain a finite ceiling. Summaries show `Unlimited` in both admission preview and final outcome.

For the existing profiles, set `monthly_microdollars` to JSON `null`, `monthly_runs` to `100`, and `approval` to `alanlima/pawlocal/issues/351` in `PAWLOCAL_ONCALL_MODEL_PROFILE` on both `oncall-development` and `oncall-production`; read back and compare all other fields. The owner-approved monthly run-count is 100 and remains enforced. Preserve token/request settings, rates, timestamps and rule UIDs. This operator-managed profile is outside configuration reconciliation. Existing ledger reservations and consumed generations remain unchanged. Accounting review is deferred to [#352](https://github.com/alanlima/pawlocal/issues/352).

### Default model: `gpt-5.4-mini`

The owner-selected generator default is `gpt-5.4-mini` with `medium` effort for fixer and reviewer. [Official Standard global pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini), reviewed 24 October 2026, is **$0.75/M input** and **$4.50/M output** tokens. The generator supplies matching integer rates `750000` and `4500000` microdollars per million tokens. Confirm current pricing, API project entitlement and pinned Action/CLI compatibility before owner approval; generating JSON does not activate a model or authorize spending.

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
| `requests_per_role` | 64 | `4` |
| `input_per_request` | 250 000 tokens | `100000` |
| `output_per_request` | 128 000 tokens | `16000` |
| `input_per_role` | ≤ `input_per_request × requests_per_role` | `200000` |
| `output_per_role` | ≤ `output_per_request × requests_per_role` | `32000` |
| `promotion_seconds` | 3 600 s (1 h) | `3600` |
| `recovery_seconds` | 600–900 s | `720` |
| `monthly_runs` | 1 000 | `20` |

---

### Per-turn output allocation

Each role reserves `min(output_per_request, output_per_role // requests_per_role)` output tokens per call. The recommended four-request profile with a 32,000-token role ceiling therefore allocates 8,000 per turn. To choose another allocation, set both request and role ceilings consistently, keep `output_per_role <= output_per_request * requests_per_role`, and obtain owner approval for the complete profile. Reasoning and answer output share the cap; deadlines and input/monthly limits remain independent.

For example, 64 calls at 126,000 output tokens require `output_per_role=8064000`; changing only the per-request ceiling does not grant that allocation. This is arithmetic, not a recommended live budget. See [output allocation and tuning](oncall-troubleshooting.md#output-allocation-and-tuning) for smaller-cap examples, refusal diagnosis and reservation accounting.

### Cost estimate

With the recommended values and `gpt-5.4-mini` Standard global pricing:

| Item | Calculation | Cost |
|---|---|---|
| Input per role (2 roles) | 200,000 tokens * 2 * $0.75/M | **$0.30** |
| Output per role (2 roles) | 32,000 tokens * 2 * $4.50/M | **$0.288** |
| **Per incident (worst-case)** | | **$0.588** |
| **Monthly ceiling (20 runs)** | $0.588 * 20 | **$11.76** |

Setting `monthly_microdollars` to `20000000` (\$20.00) gives comfortable headroom over the 20-run worst case while keeping a hard stop well below \$30.

> [!NOTE]
> `quota.py` charges the **full worst-case envelope** before forwarding — not actual usage. Failed, cancelled, or interrupted jobs remain charged. There is no automatic refund. The \$20 monthly ceiling is the outer bound, not an expected bill.

---

### Grafana Alert Rules and `rule_uids` (Decoupled & Dynamic)

Grafana notification policies and alert rules are the authoritative source of truth for which alerts should trigger on-call support.

In PawLocal, `rule_uids` in the profile is **optional** (`"rule_uids": {}`). When omitted or empty:
- The recovery observer dynamically matches the active alert rule by its `alert_name` (or alert labels) during post-incident verification.
- You can create any alert rule in the Grafana UI without needing to know or pre-configure its auto-generated Rule UID in repository logic.
- Multiple and arbitrary alert rules can be configured in Grafana and routed to the on-call contact point.

If you explicitly wish to pin an exact canonical Rule UID for automated synthetic journey rules, you can optionally supply:
| Environment | Canonical Rule UID (Optional) |
|---|---|
| **Development** | `pawlocal-development-search-detail` |
| **Production** | `pawlocal-production-search-detail` |

---

### Generating the Profile JSON

You can generate the complete, validated JSON string using the repository helper script without manual JSON formatting or timestamp math:

```bash
python ops/incident-response/generate-profile.py
```

To generate a new profile with explicit unlimited monthly spending:

```bash
python ops/incident-response/generate-profile.py --unlimited-monthly-spending --approval alanlima/pawlocal/issues/351
```

`--unlimited-monthly-spending` and finite `--monthly-budget-usd` are mutually exclusive. Generating a new profile uses the defaults below; use a field-preserving update for existing profiles.

This helper:
- Uses the owner-selected `gpt-5.4-mini` model, `medium` effort, matching rates `750000`/`4500000`, and \$20.00 monthly budget ceiling.
- Leaves `rule_uids` empty for dynamic alert matching. Pass `--dev-rule-uid <uid>` and `--prod-rule-uid <uid>` to pin reviewed UIDs.
- Automatically calculates the current UTC month (`approved_month`), UTC review timestamp (`rates_reviewed_at`), and 30-day expiration timestamp (`expires_at`).
- Runs the output through `quota.py` validation to guarantee it passes the gateway checks.

For another approved model, supply **both** reviewed `--input-rate` and `--output-rate` in microdollars per million tokens alongside `--model`. The generator rejects a model override without both rates, and rejects a one-sided rate override. It does not fetch prices or maintain a model registry. CLI usage or model metadata cannot infer approved budgets or authoritative rates; official pricing and owner policy remain required inputs. Recheck the official pricing source before generation; the generated review timestamp records that operator review, not an automated price lookup.

**Illustrative output; regenerate timestamps and review before saving to `PAWLOCAL_ONCALL_MODEL_PROFILE`:**

```json
{"model":"gpt-5.4-mini","effort":"medium","service_tier":"default","input_rate":750000,"output_rate":4500000,"monthly_microdollars":20000000,"monthly_runs":20,"promotion_seconds":3600,"recovery_seconds":720,"rule_uids":{},"requests_per_role":4,"input_per_request":100000,"output_per_request":16000,"input_per_role":200000,"output_per_role":32000,"approval":"alanlima/pawlocal/issues/269","approved_month":"2026-10","rates_source":"https://developers.openai.com/api/docs/pricing","rates_reviewed_at":"2026-10-24T03:04:03Z","expires_at":"2026-11-23T03:04:03Z"}
```

---

### Manual Profile JSON Reference

If you prefer to construct the JSON manually, satisfy all fields below:

```json
{
  "model": "gpt-5.4-mini",
  "effort": "medium",
  "service_tier": "default",
  "input_rate": 750000,
  "output_rate": 4500000,
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
  "rates_source": "https://developers.openai.com/api/docs/pricing",
  "rates_reviewed_at": "<UTC timestamp when you reviewed pricing, e.g. 2026-10-24T03:00:00Z>",
  "expires_at": "<UTC timestamp at most 31 days from rates_reviewed_at>"
}
```

**Before enabling:**

1. Visit `https://developers.openai.com/api/docs/pricing` and confirm `gpt-5.4-mini` input/output rates match `750000` / `4500000` microdollars per million tokens.
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
3. POST a signed test payload to the DEV Function URL to verify the full dispatch path:

**Bash / macOS / Linux:**
```bash
# Read the Lambda Function URL and HMAC secret from SSM
URL=$(aws ssm get-parameter \
  --name "/pawlocal/development/config/oncall/webhook-url" \
  --query Parameter.Value --output text)

SECRET=$(aws ssm get-parameter \
  --name "/pawlocal/development/secrets/grafana/webhook-hmac" \
  --with-decryption --query Parameter.Value --output text)

BODY='{"receiver":"pawlocal-development-oncall","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"pawlocal-development-search-detail-failure","environment":"development","service":"pawlocal-api"},"startsAt":"2026-10-24T00:00:00Z","endsAt":"0001-01-01T00:00:00Z","fingerprint":"0123456789abcdef01234567"}]}'

TS=$(date +%s)
SIG=$(printf '%s:%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -i -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "x-grafana-alerting-timestamp: $TS" \
  -H "x-grafana-alerting-signature: $SIG" \
  -d "$BODY"
```

**PowerShell (Windows):**
```powershell
$Url = (aws ssm get-parameter --name "/pawlocal/development/config/oncall/webhook-url" --query Parameter.Value --output text)
$Secret = (aws ssm get-parameter --name "/pawlocal/development/secrets/grafana/webhook-hmac" --with-decryption --query Parameter.Value --output text)

$Body = '{"receiver":"pawlocal-development-oncall","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"pawlocal-development-search-detail-failure","environment":"development","service":"pawlocal-api"},"startsAt":"2026-10-24T00:00:00Z","endsAt":"0001-01-01T00:00:00Z","fingerprint":"0123456789abcdef01234567"}]}'
$Ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()

$Hmac = New-Object System.Security.Cryptography.HMACSHA256
$Hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($Secret)
$Bytes = [System.Text.Encoding]::UTF8.GetBytes("$Ts`:$Body")
$Sig = [BitConverter]::ToString($Hmac.ComputeHash($Bytes)).Replace("-", "").ToLower()

Invoke-RestMethod -Uri $Url -Method POST -Headers @{
  "x-grafana-alerting-timestamp" = $Ts
  "x-grafana-alerting-signature" = $Sig
} -ContentType "application/json" -Body $Body
```

Expected response: `204 No Content` (GitHub accepted dispatch). A `502` indicates that GitHub App credentials in SSM or the Lambda receiver configuration are invalid or unauthorized; a `401` indicates an HMAC signature or timestamp verification mismatch.

4. Watch [GitHub Actions](https://github.com/<org>/<repo>/actions/workflows/incident-responder.yml) for the dispatched run.
5. Verify the development demonstration (G2 gate): preflight claim → fixer → checks → reviewer → candidate PR → CI → squash merge → development deployment → recovery verification.

> [!TIP]
> If testing with a synthetic test alert (such as the payload above with a non-firing fingerprint), preflight will log `no firing alerts selected for admission` and set `admitted=false`. This confirms dispatch, elevated ruleset verification, and Grafana Stack authentication without claiming an issue or spending model quota. If preflight fails with `HTTP Error 401: Unauthorized`, see [Layer 4 troubleshooting](oncall-troubleshooting.md#layer-4--preflight-admission--alert-verification).

> [!NOTE]
> If `oncall-production` is not yet enabled, the run will verify development recovery and cleanly stop before production promotion. To test the full autonomous loop through production recovery, enable `PAWLOCAL_ONCALL_ENABLED=true` and `PAWLOCAL_PRODUCTION_TELEMETRY_READ_APPROVED=true` in `oncall-production` as well.

---

## Step 11 — Activate the Grafana contact point (DEV)

### Search/detail alert query

In **Alerts & IRM** → **Alerting** → **Alert rules**, configure query **A** with the Prometheus data source and query type **Instant**. Use the expression for the target environment below and set the alert condition to **A is above 0** (a positive rate of search/detail 5xx responses).

**Development:**

```promql
sum(rate(pawlocal_api_requests_total{environment="development",service="pawlocal-api",route=~"/api/v1/places.*",status_class="5xx"}[2m])) or (0 * sum(rate(pawlocal_api_requests_total{environment="development",service="pawlocal-api",route=~"/api/v1/places.*"}[2m])))
```

**Production:**

```promql
sum(rate(pawlocal_api_requests_total{environment="production",service="pawlocal-api",route=~"/api/v1/places.*",status_class="5xx"}[2m])) or (0 * sum(rate(pawlocal_api_requests_total{environment="production",service="pawlocal-api",route=~"/api/v1/places.*"}[2m])))
```

The traffic-based fallback returns **0** when matching request metrics have enough samples for the two-minute rate but no 5xx series exists. If neither side has data, the result remains **No Data**; absent telemetry does not establish healthy recovery. Keep No Data and query errors visible rather than mapping them to Normal.

Use the matching rule name (`alertname`) `pawlocal-development-search-detail-failure` or `pawlocal-production-search-detail-failure`, and explicitly set rule labels `environment=development` or `environment=production` and `service=pawlocal-api`. The sums remove metric labels, so these rule labels are required for notification routing. See [Grafana-managed alert rule configuration](https://grafana.com/docs/grafana/latest/alerting/alerting-rules/create-grafana-managed-rule/) for query and condition controls.

### Activate development routing

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
3. Configure the [search/detail alert query](#searchdetail-alert-query) with the production expression, rule name and labels, then assign the contact point to a notification policy matching `environment=production`, `service=pawlocal-api` alerts.
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
2. Update the SSM parameter `/pawlocal/<env>/secrets/oncall/dispatch-app-private-key` for **both** environments.
3. Test that a signed alert reaches GitHub and dispatches a workflow run (the receiver must return HTTP `204 No Content`; an HTTP `502` means the App key or permissions are invalid; an HTTP `401` indicates an HMAC signature or timestamp mismatch).
4. Verify that a test workflow run is dispatched in GitHub Actions.
5. Only after confirming a successful 204 response and dispatched run, delete the old private key from the GitHub App settings.

### Rotate the Publisher App private key

1. Generate a new private key in the GitHub App settings.
2. Update `PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY` in all affected GitHub Environments (`oncall-development`, `oncall-production`, `incident-change-authorization`, `ordinary-change-approval`).
3. Trigger a test workflow run to confirm the new key mints a valid token.
4. Delete the old key.

---

## Verification checklist before going live

| Check | How to verify |
|---|---|
| Unsigned POST → 401 | `curl -X POST <function-url> -H "Content-Type: application/json" -d '{}'` |
| Unauthorized service → 403 | Signed POST with service not in `allowed_services` |
| Valid alert → 204 | Signed POST with correct alert shape dispatches workflow (502 indicates App auth/dispatch failure) |
| Missing `OPENAI_API_KEY` → workflow fails closed | Remove the secret, dispatch a test, confirm job exits without calling OpenAI |
| Ledger issue closed → admission denied | Close the quota issue, send a valid alert, confirm the workflow exits at preflight |
| Ordinary PR change authorization | Open a normal PR and confirm change authorization workflow passes |
| DEV dashboards show 0 PROD data | Run dashboard test: `terraform test -filter=dashboards.tftest.hcl` |

---

## Related documentation

- [On-call responder troubleshooting guide](oncall-troubleshooting.md)

- [Incident responder specification](specs/incident-responder.md)
- [Hosted telemetry operations](hosted-telemetry-operations.md)
- [Signed Lambda receiver README](../ops/incident-response/README.md)
- [Trusted workflow README](../ops/incident-response/ACTIONS.md)
- [GitHub Actions workflow reference](github-actions.md)
- [Terraform operator guide](terraform-greenfield-operations.md)
- [Configuration inventory](configuration-inventory.md)
- [Monitoring and incident response wiki](https://github.com/alanlima/pawlocal/wiki/Monitoring-and-incident-response)

## Temporary incident enforcement mode (#375 / DEC-017)

`PAWLOCAL_ONCALL_ENFORCE_GUARDS` defaults to `false`. Missing, empty and exact `false` disable **all software policy guards within the incident response run and its participating shared consumers**; exact `true` restores enforcement. Other values are configuration errors. This supersedes earlier descriptions in this guide that call those run policies mandatory. Guard selection and reinstatement are deferred to [#374](https://github.com/alanlima/pawlocal/issues/374).

Configure `PAWLOCAL_ONCALL_ENFORCE_GUARDS` as a public **GitHub Environment variable** in `oncall-development` and/or `oncall-production`. The matching Environment value overrides the repository fallback; missing/empty values default to `false`. Resolution runs in a step after the runner enters the selected on-call Environment, so a repository `false` cannot mask an Environment `true`. This operator control is intentionally outside Parameter Store synchronization because it governs trusted automation policy, not application configuration.

Each incident workflow snapshots its configured source Environment's selected mode in preflight and passes that output to every later job and policy predicate, including development and production phases. Editing a variable affects new resolver executions; it does not change the mode of an already-running controller. Shared change authorization independently resolves its current source Environment from the bounded `incident/{environment}/{key}` branch routing hint, then passes that mode to its status and authorization jobs. The hint selects configuration, not authorization. Production dispatch carries the optional `incident_environment` source selector; its resolver enters that on-call Environment and passes the chosen mode to the reusable Terraform workflow as `enforce_guards`. Ordinary authorization and ordinary release calls retain `true`. See [GitHub vars context availability](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#vars-context).

In disabled mode, a structurally supported `incident/` branch selects the incident authorization route without actor/main/draft policy checks; its status states that verification was skipped. Shared production bypass applies to the incident-controller source-assertion route (`expected_workflow_sha` supplied), while ordinary production eligibility remains enforced. Neither routing hint is authenticated when enforcement is disabled.

The webhook receiver Lambda is outside this toggle and retains its existing signature, timestamp, payload, allow-list and dispatch checks. Firing-only event routing is also unconditional: the receiver acknowledges valid resolved-only notifications without dispatch and forwards only firing records from mixed groups; controller admission independently ignores non-firing records before profile, issue, quota or model work.

The firing event requirement and cancellation handling are operational minimums in both modes: a cancelled controller cannot publish a PR; its finalizer still records the outcome. The pinned Codex action bot permission guard remains active in both modes: the configured dispatcher bot is admitted explicitly, and other bots retain the existing repository write-permission fallback. Disabled mode supplies an actual-actor override only for human actors. See [Codex action actor inputs](oncall-troubleshooting.md#symptom-codex-action-rejects-allow-bot-users-before-model-execution).

| Covered policy | Decision sites | Disabled behavior | Enabled behavior / evidence |
|---|---|---|---|
| Actor/main/attempt, activation, production telemetry approval, readiness/protection configuration | `admission.py`, `protection.py`, `control.py`, incident workflow, `publisher-token.mjs` | Admit usable configured incident inputs without these policy verdicts | Original trusted admission and readiness checks; `enforcement` metadata and bounded log entries identify disabled categories |
| Alert generation/identity/continuity, deduplication and one-attempt lease | `admission.py`, `control.py`, `quota.py`, `promotion.py` | Skip continuity/duplicate policy vetoes; retain real incident/run identifiers | Original fresh generation and claim checks |
| Monthly/request/role/token budgets, emergency stop and internal deadlines | `quota.py`, `quota_gateway.py`, `deadline.py`, broker helpers | Skip internal policy ceilings/stop decisions; keep real usage/accounting and finite network timeouts | Original approved profile limits and deadlines; bounded skipped evidence |
| Candidate paths/identity, reproduction/check verdicts and reviewer verdict | `candidate.py`, `checks.py`, `job.py`, `publisher.py` | Skip candidate policy test execution with null results and explicit skipped evidence; run the review model and retain its actual response | Original candidate/check/review requirements; never turn skipped or failed tests/review into a passed result |
| Publication/merge provenance, required-CI software verdict and authorization status | `publisher.py`, `promotion.py`, shared `authorizer.py`, token broker | Skip incident policy rejection; preserve actual GitHub API acknowledgements | Original immutable provenance/CI requirements; ordinary authorization unchanged |
| Development/production release provenance and incident eligibility | `promotion.py`, shared `guards.py`, production eligibility helpers | Skip incident-only policy verdicts; retain actual commit/image/run identifiers, deployments and API errors | Original lineage and development-release policy |
| Rule health/schema/generation, stable recovery window and finalization | `recovery.py`, `promotion.py`, `finalize.py`, `receipts.py` | No stable-window wait; record `recovery_verified: false` and no fabricated observations/proof | Original real public journey/rule recovery verification; disabled receipts carry `enforcement` mode |

Externally enforced controls still block independently: GitHub required checks/rulesets and protected Environment approvals/branch policies, App installation permissions, AWS IAM/OIDC permissions, provider/service quotas, Actions concurrency and hard job timeouts. The flag neither changes these settings nor turns rejected API calls into successes. Actual operational requirements remain: parseable required configuration and payloads, usable private keys/tokens/targets, bounded transport decoding, genuine source/image/artifact identifiers and real API/deployment acknowledgements. Pre-merge model/test execution remains isolated from publication, telemetry, deployment and GitHub credentials. Candidate transport supports source deletion in disabled mode; it still cannot represent symlinks or special files; finite file/payload bounds and safe filesystem decoding remain mechanical requirements. The gateway still needs supported parseable Responses API messages, local text/tool shapes and actual provider acknowledgements; unsupported remote/stored input or malformed protocol data remains an error. These execution/transport constraints are outside the policy switch and must not be reported as skipped guard successes.

Disabled candidate-path enforcement permits changes to infrastructure and operational code. After merge, that code may execute in normal release jobs with their existing credentials. The isolation guarantee covers pre-merge model and test processes only; disabled mode does not provide the former post-merge protection against candidate code running in credential-bearing jobs. This does not authorize intentional credential printing/exfiltration, new IAM permissions or live settings changes.

Disabled mode is an explicitly unverified policy bypass, not successful recovery evidence. A previously failed run cannot resume merely because this flag or source changes. Current main containing a repair does not demonstrate another fix attempt or production recovery.
