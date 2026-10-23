# Grafana Cloud bindings and provisioning (#224)

Implementation is present; **live Free-plan access, credentials, origins, quotas and per-signal isolation remain pending; the existing shared stack and region are identified**. Both checked-in environment bindings are disabled/null. No live requests, registration, token creation, Grafana mutation or AWS apply was performed to deliver this package.

## Ownership

`bindings.json` and `provision.py` own only the public PawLocal folder and Faro application in each explicitly enabled environment. The tool reads existing stack metadata and metrics/Loki/Tempo datasource bindings; it does not create or alter datasources/credentials. It never deletes/recreates Faro apps, creates a stack, changes account billing, provisions dashboards/alerts/contact points, creates tokens, or calls AWS. Six dashboards and alerting belong to #226; direct SDK export belongs to #225; synchronization belongs to #223.

Grafana resources use one source-controlled **API** owner. Terraform could manage these public objects with provider credentials supplied through environment variables, but this implementation deliberately uses the documented APIs instead. Do not also declare the same folder/Faro app in Terraform. Existing bootstrap/development/production Terraform states exclusively retain AWS ownership: no fourth state, new provider or default AWS-plan authentication dependency is introduced. Public handoff values become reviewed input to matching Terraform-owned SSM String producers in #223/#225; never write SSM through this tool or a shell command.

## Shared Free stack

Use one operator-configured Grafana Cloud stack for all environments, with separate development and production Faro applications. Keep account identifiers, stack URLs and regional connection values in deployment configuration. Discover the actual bindings through the read-only command below. Free is the intended operating limit: trial or paid allowances do not establish Free eligibility.

Datasource bindings, exact origins, scopes, post-trial Free quotas and per-signal authorization require verification. Checked-in bindings remain disabled/null until required inputs and initial setup reviews exist. Withhold signals or reads that cannot satisfy the shared-stack privacy boundary and record the required setup decision.

## Operator setup and approval record

1. Select an existing, owner-approved Grafana Free account/stack and region. Record actual residency, retention, account-wide quota evidence and approval reference. Free currently includes **one stack** per account; two Faro apps/folders do not create independent data tenants or double allowances. Check [Cloud API stack limits](https://grafana.com/docs/grafana-cloud/learn-and-build/developer-resources/api-reference/cloud-api/#stacks) and actual [pricing/usage](https://grafana.com/pricing/).
2. Obtain the exact deployed frontend origin for each environment from authoritative release/configuration evidence. No wildcard, localhost, guessed domain, path, query or credential-bearing URL is accepted. Approve any origin change explicitly. Inspect the actual stack ID/slug/URL/region, OTLP connection endpoint/instance ID, regional Faro **management API** URL, and existing datasource UID/name for metrics/logs/traces. Faro management URLs differ from collector URLs and have regional/creation-date exceptions; use the approved actual endpoint, not a generated hostname.
3. Populate the corresponding binding and set `enabled: true` only in a reviewed configuration change. The complete field contract is enforced by `validate_manifest`; unknown fields/duplicate keys are errors. `approval` contains `reference`, `residency`, `free_plan_verified: true`, `quota_review`, `isolation_review`. These are review references, not proof fabricated by the tool. `plan` additionally checks actual remote stack ID/slug/URL/region, the public OTLP connection endpoint and existing datasource UID/name/type. The OTLP username equals the actual Grafana stack ID as documented by the pinned provider; it is not a Prometheus/Loki tenant ID. Residency/account quota evidence still needs owner review.
4. Review narrowly scoped operator tokens with expiry: `GRAFANA_CLOUD_ACCESS_POLICY_TOKEN` for stack metadata (`stacks:read`), `GRAFANA_FARO_ACCESS_POLICY_TOKEN` (optional narrower token; otherwise the Cloud policy token) for matching-stack `frontend-observability:read`/`frontend-observability:write` (no delete), and `GRAFANA_SERVICE_ACCOUNT_TOKEN` for matching Grafana folder create/read and datasource read. Confirm actual Free-plan role/scope availability. These are intentionally operator inputs outside SSM/GitHub synchronization and outside Terraform state; this tool does not create them. Supply through a credential manager/hidden prompt to the current process environment, never source files, arguments, outputs or artifacts.
5. Before **production** provisioning or any production reads, prove metrics/logs/traces/Faro isolation for the selected account, token and datasource scopes. Grafana label policies apply to supported metrics/log read paths; a development label/folder alone does not restrict Tempo traces. The selected shared Free stack remains the design. If a signal cannot enforce the required read/privacy boundary, withhold that signal/read and keep its activation disabled pending an explicit owner decision. Do not silently select separate accounts, upgrade a plan or broaden tokens.

Enabled binding example structure (actual values required; not executable defaults):

```json
{
  "enabled": true,
  "stack": {
    "id": 123,
    "slug": "approved-stack",
    "url": "https://approved-stack.grafana.net",
    "region": "actual-region-slug",
    "faro_api_url": "https://actual-faro-api.grafana.net/faro",
    "otlp_endpoint": "https://actual-otlp-gateway.grafana.net/otlp",
    "otlp_instance_id": "123"
  },
  "frontend_origin": "https://actual-deployed-origin.org",
  "datasources": {
    "metrics": {"uid": "actual-metrics-uid", "name": "actual-metrics-name"},
    "logs": {"uid": "actual-logs-uid", "name": "actual-logs-name"},
    "traces": {"uid": "actual-traces-uid", "name": "actual-traces-name"}
  },
  "approval": {
    "reference": "reviewed-issue-or-run-link",
    "residency": "reviewed-actual-region-and-data-residency",
    "free_plan_verified": true,
    "quota_review": "account-wide-quota-evidence-link",
    "isolation_review": "per-signal-access-proof-or-dev-only-limitation"
  }
}
```

## Validate, plan, provision and verify

Supply the approved existing stack URL and actual Grafana region as command inputs. The example uses placeholders; replace them with deployment configuration values. Discovery reads stack metadata, connections and datasources, and returns selected public candidate bindings with no mutations:

```powershell
python observability/grafana/cloud/provision.py --environment development --mode discover --stack-url https://approved-stack.grafana.net --region actual-region-slug
```

Discovery derives stack ID, OTLP endpoint/username, datasource UID/names and regional Faro management endpoint from actual metadata plus the pinned official regional rules (including creation-date exceptions). Multiple datasource candidates return `needs-selection-not-approved`, partial bindings and bounded public candidate UID/name/type metadata rather than guessing. Review the candidates, then rerun discovery with `--datasource-uids-json '{"metrics":"reviewed-metrics-uid"}'` (optional keys: `metrics`, `logs`, `traces`). Every supplied UID must occur exactly once in that stack and match the corresponding signal type, even when a type otherwise has only one candidate. Discovery output is not an enabled manifest or approval; unresolved discovery cannot be submitted as plan/apply bindings. The remaining review input is the exact frontend origin from existing release evidence, plus approval/privacy/isolation/quota references. Do not invent values or claim discovery verifies quota/authorization. The Faro collector URL comes from creating/reading the app, not from a user-entered key. Two credential domains suffice: Cloud policy (stack/Faro scopes) and Grafana service-account token; a separate narrow Faro token is optional when supplied as `GRAFANA_FARO_ACCESS_POLICY_TOKEN`.

Commands run from repository root. The default `check` performs **zero network calls**, including enabled bindings. Disabled `plan`/`apply` also perform no network calls and need no credentials.

```powershell
python observability/grafana/cloud/provision.py --environment development --mode check
python -m unittest discover -s observability/grafana/cloud/tests -v
```

After actual operator credentials and explicit live setup authorization are supplied:

```powershell
python observability/grafana/cloud/provision.py --environment development --mode plan
python observability/grafana/cloud/provision.py --environment development --mode apply
python observability/grafana/cloud/provision.py --environment development --mode plan
```

`plan` reads only. All collision/identity/datasource checks complete before writes. An existing app must carry the exact ownership marker; a foreign name/UID stops rather than being adopted. Only a missing `pawlocal-<environment>` folder and matching app are created. Origin/settings drift updates the same app ID using PUT; no DELETE path exists. Desired Faro settings disable geolocation/lab-data combination and attach only stable owner/environment attributes. SDK-side privacy/sampling is still #225, not established by this configuration alone. Allow the documented CORS propagation window and verify permitted/foreign browser origins separately before activation.

`apply` reads back folder/app settings. Repeated apply with matching objects has no writes. The output is an explicitly selected **public-only** handoff: stack/region, stable folder UID, datasource UID/names, and exact `/pawlocal/<environment>/config/grafana/{stack-url,otlp-endpoint,otlp-instance-id,faro-collector-url}` values. Collector URL includes the supported public Faro app key; it is not an ingestion/query credential. No arbitrary API response body is serialized. Private token/HMAC/credential setup stays under the approved #223 runtime-secret procedure.

No automatic retry of a mutation follows a timeout. A request might have succeeded before its response was lost: run `plan`, inspect current owned objects, then approve a retry if necessary. Partial creation is safe to inspect/reconcile; retain the same app/UID and never delete to fix an error. HTTP auth failures stop; redirects are rejected to avoid forwarding credentials to a new host. Fix the binding/access through review rather than disabling TLS or bypassing identity checks.

## Disable, recover, rotate and measure

- **Disable telemetry** through the matching reviewed release/runtime toggle under #225/#223. `enabled: false` here disables this provisioning command only; it does not switch off already deployed SDKs or delete existing Grafana resources. After source setup exists, retain its reviewed binding externally/in Git history before returning the disabled/null template. Do not claim this flag stops billing.
- **Recover** by correcting the reviewed binding, running read-only plan, then the approved API reconciliation. Revalidate exact origin, collector URL, app ID, read scopes and original journey. Reuse stable IDs; rollback an origin/settings change with the reviewed previous binding, not deletion.
- **Rotate operator tokens** outside source/state through the approved credential owner, replace process environment values, verify read-only plan, then revoke retired tokens using the approved owner procedure. Token creation/revocation is not implemented here. Runtime ingestion/query/HMAC rotation remains #223; never put those values in the public handoff.
- **Measure usage** in the actual account Usage/Billing views per signal and account. Track active series, logs/traces GB, Faro sessions and synthetic executions; two environments share applicable allowances. New frontend accounts may count sessions, logs and traces independently. Review quota/no-data/outage evidence before G1; lower SDK sample/label volume through #225 before a quota is exhausted. Responder model/admission quotas require separate owner approval and are not Grafana quota enforcement.
- **Close only with evidence:** record actual account/region/Free setup, credentials/scope review (metadata only), origins, repeat plan/apply/noop evidence, public handoff, isolation limitations and independent review. Missing account credentials blocks live activation/closure, not this mock-tested implementation delivery. Production remains separately approved under #230/#231.

## Development-only hosted launcher

`grafana-development-setup.yml` runs this provisioner on GitHub-hosted Ubuntu
from trusted main, under the existing protected `development-apply` Environment.
It uses existing Cloud/Faro policy and stack service-account secrets; credentials
are never dispatch inputs. The default `discover` mode takes actual `stack_url`
and `region`, performs GETs only and emits the public stack/datasource metadata.
If selection is needed, review the bounded `datasource_candidates`, then rerun
with optional `datasource_uids_json` (for example `{"metrics":"reviewed-uid"}`).
Do not treat candidate metadata as approved bindings.
It does not create a Faro collector before an application exists.

Review that evidence, the actual development frontend origin, residency, shared
Free quota and isolation constraints before preparing an enabled development
manifest. Keep production disabled with all its bindings null. For `plan` or
`apply`, supply that JSON as `public_bindings_json`, the reviewed origin as
`frontend_origin`, and leave discovery-only stack/region/selector inputs empty. Run plan
first and independently review its exact folder/Faro changes before apply. The
launcher rejects production enablement, duplicate fields, mixed mode inputs and
origin mismatch before any remote request. Successful apply returns the actual
public Faro collector URL; never manufacture an app key or approval reference.

Only the existing selected-development folder/Faro reconciler is reachable.
No dashboard/alert/experience/synthetic code is imported; no AWS permission is
granted. The public handoff is retained for seven days. Timeout or uncertain
mutation requires a new read-only plan, never an automatic retry. Application
activation still needs its separate public Terraform input, exact runtime secret,
reviewed development IAM plan and verified release. This launcher is not G1 or
proof of accepted telemetry.

## API compatibility and sources

Reviewed on 23 October 2026. The custom adapter contract is pinned to the official [Grafana provider v4.50.0 Faro client](https://github.com/grafana/terraform-provider-grafana/blob/v4.50.0/internal/common/frontendo11yapi/client.go) and [resource/model mapping](https://github.com/grafana/terraform-provider-grafana/blob/v4.50.0/internal/resources/frontendo11y/models.go): `/faro/api/v1/app`, stack-scoped `Bearer <stackID>:<token>` plus `X-Scope-OrgID`, CORS origins/labels/settings and collector endpoint plus public app key. This is a protocol reference, **not a provider dependency**. The Faro management endpoint is not listed as a general Cloud API endpoint; treat this pinned provider implementation as the compatibility boundary and revalidate it before any live rollout/API upgrade.

The stack-ID OTLP username contract is documented in the pinned [cloud-stack data source](https://github.com/grafana/terraform-provider-grafana/blob/v4.50.0/docs/data-sources/cloud_stack.md).

Other primary sources: [Cloud API metadata/connections](https://grafana.com/docs/grafana-cloud/learn-and-build/developer-resources/api-reference/cloud-api/), [folder API](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/folder/), [datasource API](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/data_source/), [Faro provisioning/scopes](https://grafana.com/docs/grafana-cloud/developer-resources/infrastructure-as-code/terraform/terraform-frontend-observability/), [Faro setup/origins](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-applications/frontend-observability/instrument/faro/), and [per-signal policy limitations](https://grafana.com/docs/grafana-cloud/security-and-account-management/authentication-and-permissions/access-policies/).

The offline tests and disabled-manifest checks run in the existing Compose PR/main CI job, whose `observability/**` path selector covers this package. They use no cloud credentials or live endpoints. Terraform files are unchanged, so no new provider/init/validate gate is needed for the API-only implementation.
