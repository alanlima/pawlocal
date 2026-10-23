# Six dashboards and native synthetic journey (#226)

**Implemented and offline tested; G1/live acceptance is pending.** This package is stacked on #224's Grafana API owner. No live Grafana mutation, credential creation, scheduled check activation, AWS mutation or production fault was performed. `experience.json` is disabled and inactive; responder routing is separately off.

## Selected setup and dependencies

The owner selected `https://alanlima.grafana.net/` as one shared stack for all environments, with **Free as the intended operating limit**. Read-only UI discovery identified stack/OTLP username `1880841` and `https://otlp-gateway-prod-au-southeast-1.grafana.net/otlp`; Grafana region `prod-au-southeast-1` (Australia) and AWS region `ap-southeast-2` were confirmed in the stack details UI. The UI also showed a trial with 10 days remaining: do not treat paid/trial features or quotas as verified Free entitlement. These are observed public setup facts, not activation authorization. #224's binding stays disabled until actual inputs and account/privacy/cost reviews are complete. Separate accounts are not selected; withhold reads/signals that cannot be safely authorized in the shared stack.

#225 supplies the telemetry contract below. The actual backend/Faro release, privacy, exporter behavior and Cloud ingestion must be independently verified before G1. #227 supplies the signed receiver only after its reviewed setup; live responder routing is not a prerequisite for monitoring acceptance. #230/#231 retain production gates; this implementation provisions **development** checks/rules only.

## Stable dashboard and signal contract

`build_dashboards.py` is the definition source; the six checked-in `dashboards/*.json` must regenerate exactly. This generator builds operational Grafana dashboard JSON, not presentation diagrams or vendor image assets.

| UID | Main support questions |
|---|---|
| `pawlocal-journey` | Search/details requests, API latency/errors and external journey health |
| `pawlocal-application` | Bounded route/status classes, p95 latency and redacted application logs |
| `pawlocal-dependencies` | DSQL/PostgreSQL query latency, outcomes and safe dependency events |
| `pawlocal-releases` | Request/error/latency comparisons by immutable image digest |
| `pawlocal-telemetry` | Completed/failed exports, no data and actual shared-account usage |
| `pawlocal-incidents` | Failing journey/routes, safe logs with trace IDs and related Tempo traces |

All dashboards use environment, service and release variables, consistent units/time ranges, stable incident/Explore/usage navigation and `NO DATA / UNKNOWN` display. Variables are not access controls. Metric-to-log/trace navigation must be proven against actual data before G1; templates do not claim a live screenshot or trace correlation result.

#225 explicitly emits metric labels `environment`, `service=pawlocal-api`, `release` (the validated `sha256:<digest>`), plus bounded operation labels. Queries do not assume Grafana automatically promotes every resource attribute:

- `pawlocal_api_requests_total`: `route` template, `method`, `status_class`, `outcome`; route values include `/api/v1/places` and `/api/v1/places/{place_id}`.
- `pawlocal_api_duration_seconds_bucket`: same bounded API labels, seconds.
- `pawlocal_dependency_requests_total` and `pawlocal_dependency_duration_seconds_bucket`: `dependency=aurora_dsql|postgresql`, fixed `operation=query`, `outcome`.
- `pawlocal_telemetry_exports_total` and `pawlocal_telemetry_export_failures_total`: `signal=traces|logs|metrics`. Failure samples may not exist before the first failure; panels never fill absence with zero.
- Cloud log JSON includes environment/service/release and safe event_code/operation/outcome/http_status/duration_ms/trace_id/span_id. The Loki stream selector uses the supported OTLP `service_name` mapping; JSON filters select explicit body fields. Verify that actual mapping and parse before G1. TraceQL uses `service.name`, `deployment.environment.name`, `service.version` resource attributes.

Metrics/logs/traces datasource UIDs come from #224. A separate existing `grafanacloud-usage` Prometheus datasource UID provides active series, active log streams and trace bytes/sec. Usage panels are **account/shared quota** views, not per-environment allocations; logs/traces monthly usage and all actual allowances are reviewed in the linked account Usage page. The setup service account needs appropriate billing/usage-reader access. No datasource credential is created or altered here.

## Native Synthetic Monitoring contract

One **managed public probe**, one scripted API check, every **300 seconds**, timeout **10 seconds**. The source script reads only the approved API base: GET `/places?page_size=1`, validate one published UUID, then GET that ID's details and assert it matches. It sends no authentication/private ingest token, logs no body/search text, follows no redirects, bounds response parsing, and replaces request names with route templates. k6 system `url` tags are excluded so place IDs cannot become request-name/URL metric dimensions. No remote JavaScript imports or additional AWS/GitHub probe server are introduced.

The API contract is pinned to [synthetic-monitoring-api-go-client v0.20.5](https://github.com/grafana/synthetic-monitoring-api-go-client/blob/v0.20.5/docs/API.md) and [agent v0.62.0 protobuf JSON](https://github.com/grafana/synthetic-monitoring-agent/blob/v0.62.0/pkg/pb/synthetic_monitoring/checks.proto), the versions used by Grafana provider v4.50.0. Script bytes are base64 encoded in `settings.scripted.script`. Native check add/update/list/get uses `/api/v1/check/*`; probe discovery uses `/api/v1/probe/list`. Read-only `/tenant` verifies the SM token's actual stack identity before writes; tenant remote credentials are never serialized.

The official [check metric contract](https://grafana.com/docs/grafana-cloud/observe-and-act/testing/synthetic-monitoring/analyze-results/check-metrics/) defines `probe_success` for all check types; the [system label contract](https://grafana.com/docs/grafana-cloud/observe-and-act/testing/synthetic-monitoring/system-labels/) defines `job` on all check metrics. Native custom labels can be prefixed depending on tenant label mode. The synthetic panels and rule therefore select the exact stable system `job` name, rather than guessing the tenant's label migration state. Rule notification labels explicitly include development/service/route for #227. No global tenant-label migration occurs.

For a 30-day month: `1 probe × 1 check × ceil(10 seconds / 1 minute) × 43,200 / 5 = 8,640` billable API execution units at the bounded duration, below the advertised 100,000 API allowance **before other account checks**. Scripted checks are API tests; generated logs/metrics/active series also consume their own allowances. Confirm actual Free eligibility, totals and calculator before activation; startup/duration and billing measurements are acceptance evidence, not assumed zero cost. [Official billing formula](https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/synthetic-monitoring/), [scripted options/tags](https://grafana.com/docs/grafana-cloud/observe-and-act/testing/synthetic-monitoring/create-checks/checks/k6/).

## Alert, unknown health and routing

`pawlocal-development-search-detail-failure` evaluates the average native `probe_success` over 10 minutes every minute. Values below 1 remain pending for 5 minutes; recovery requires the failure to leave the 10-minute window and a further 2-minute keep-firing interval. Test actual evaluation timing before accepting it. Missing probe data produces **NoData**, query failure produces **Error**; neither is represented as healthy. `DatasourceNoData`/`DatasourceError` notifications retain the existing operator routing and are never allowlisted for a coding agent.

The rule group and synthetic check are provisioned paused/disabled while `active: false`. A reviewed source change plus explicit setup/activation approval is required to run them. `enabled: false` disables the provisioner, not already-created remote resources; use a reviewed `active: false` reconciliation to pause an existing check/rule.

Monitoring acceptance can complete with `responder_routing: false`: no receiver URL/HMAC/contact-point is required and no agent route is installed. After G1 and #227 acceptance, a separately reviewed `responder_approval` may enable the signed route. The contact point sends firing **and resolved**, caps grouped alerts at 20, uses the exact Lambda Function URL and the agreed HMAC signature/timestamp header names. Trusted setup reads the exact runtime HMAC through its approved secret procedure; pass it as `PAWLOCAL_GRAFANA_WEBHOOK_HMAC` in the ephemeral operator process, never source/arguments/state/output. No HMAC GitHub synchronization or backend ingest-token copying is added.

The API owner appends/removes only its specific notification subroute, matched by alertname/environment/service/owner label. It preserves the reviewed operator root and unrelated routes. Current upstream docs mark notification provisioning endpoints deprecated; verify the actual stack API compatibility and migration requirements before live setup. The shared-tree PUT alone sends `X-Disable-Provenance: true` to preserve operator UI editing; owned rules/contact points retain API provenance. See the [official provenance contract](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/http-api-provisioning/#edit-resources-in-the-grafana-ui). A collision fails, policy is re-read before its narrow update, and the result is verified. Because the API has no shared-tree transaction lock, **serialize all notification-policy writers** and independently review the complete proposed tree before live mutation; a concurrent external writer is a stop condition. This shared-policy operation is explicit, not silently authorized by owning a dashboard.

Secret write acceptance is opaque: repeated apply may rewrite only the supplied contact-point HMAC while public objects remain no-ops. Report only API acceptance/public metadata read-back, never secret plaintext equality. No resource DELETE/recreate path is provided.

## Setup, plan and apply boundaries

Keep #224 bindings configured only from actual discovery and approved origins. Populate `experience.json` public settings after review: usage datasource UID, actual regional SM API origin, one online public probe ID, approved `https://api-dev.<domain>/api/v1` base URL matching the reviewed development Faro origin `https://pawlocal-dev.<domain>`, existing operator receiver name and setup approval reference. Leave `active` false until activation is approved. Leave `responder_routing` false until G1/#227 and its approval reference exist; only then supply the reviewed webhook URL and runtime HMAC.

Protected operator inputs outside SSM synchronization are #224's Cloud/Faro policy and Grafana service-account tokens, plus the existing tenant's `GRAFANA_SYNTHETIC_MONITORING_TOKEN`. The tool does not register a tenant, create a token or add a probe. Verify actual scopes/entitlements and revoke/rotate through the separately approved owner process. No AWS CLI/API write, Terraform apply or new state is used by this Grafana-only API owner.

```powershell
python observability/grafana/cloud/experience.py --mode check
python -m unittest discover -s observability/grafana/cloud/tests -v
```

After account/secret/setup authorization (not executed for this implementation):

```powershell
python observability/grafana/cloud/experience.py --mode plan
python observability/grafana/cloud/experience.py --mode apply
python observability/grafana/cloud/experience.py --mode plan
```

All resource/ownership checks precede writes. Existing dashboard versions protect updates; foreign UIDs/rules/jobs/contact destinations fail closed. Native checks update their existing check/tenant IDs. Read back imported definitions and run plan again; no-op public resources are stable, while opaque HMAC write behavior is explicit. On partial failure/timeouts, inspect actual objects and re-plan; never delete resources or assume a lost response means no write occurred.

Offline CI parses all PromQL with pinned official Prometheus Lezer parser 0.315.1, validates generated JSON/labels and executes the synthetic JavaScript with mocked HTTP for success, missing data, foreign IDs and mismatched details. This does not replace a live Grafana/SM validation. CI uses no account credentials and makes no Grafana requests.

## G1 evidence and safe demonstration

Before G1: accepted #225 development release/digest, six working dashboards, actual query results and metrics-to-log/trace navigation; scoped reads/JSON/source privacy; measured ingestion/Faro/synthetic/account usage; export outage/disabled/recovery behavior; actual signed firing/resolved delivery after the applicable routing gate. Record screenshots/exports and exact release/run identities, not a generic green workflow.

Demonstrate synthetic alerting **only in development** with responder routing off. An approved temporary check assertion against the existing read-only development journey can deliberately fail without changing application data or introducing a production fault endpoint. Record the exact temporary check change, failed probe, pending/firing/operator notification, restore the source-controlled assertion, and observe stable recovery. This tests the monitoring pipeline; it does not prove an application defect or authorize a coding run. P7 separately demonstrates a real reproducible application regression/fix loop after G1. Exercise absent probe data and datasource errors as unknown/operator conditions, then restore and verify. Do not fake production traffic/health or treat an altered assertion as a deployed application outage.

Emergency sequence: set reviewed `active: false` to pause check/rule; set `responder_routing: false` to remove only the owned agent route while preserving operator policy; verify remote states and in-flight incident escalation. Reenable only after cause/cost/privacy review and repeated live checks. G1 remains an independent reviewer/owner decision; this package's merge cannot claim it.

Additional primary schema sources: [Grafana alert group/rule models at provider-pinned 1c43014c9904](https://github.com/grafana/grafana-openapi-client-go/blob/1c43014c9904/models/alert_rule_group.go), [webhook/HMAC schema at a42225b6](https://github.com/grafana/alerting/blob/a42225b6ccade6522b29cf4e10df4c6e4c2f7a13/receivers/webhook/v1/config.go), [usage signals](https://grafana.com/docs/grafana-cloud/platform/cost-management-and-billing/understand-usage-cost/metrics/), [usage limits](https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/usage-limits/).
