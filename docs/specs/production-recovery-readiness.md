# Proposed production monitoring readiness plan (#333)

**Proposal only.** No rule payload is ready to apply, no AWS saved plan exists, and production on-call enablement remains held. This document separates public initial setup from the blocked runtime credential lifecycle in #241. A documentation merge does not activate either.

## Verified readiness and blockers

The development release at `61a9988fb49708c9d1a41fc50136e74994d40d05` completed [run 40102484649](https://github.com/alanlima/pawlocal/actions/runs/40102484649). Production frontend, API health and places reads are successful. These facts do not establish telemetry ingestion or recovery readiness.

Read-only Grafana inspection found one PawLocal development application rule and no production-labelled rule. Other account/plugin/recording rules exist; the PawLocal-only count is not account-wide quota evidence. A global instant query, `count by(environment,service)(pawlocal_api_requests_total)`, returned development/pawlocal-api only, with four series. Production error, all-status and fallback queries returned no samples. Production exporter logs repeatedly report `Telemetry credential unavailable`; the existing production OTLP parameter is String and the runtime requires SecureString. Legacy Terraform ownership remains unverified. Resolve the separate [proposed production secret decision](production-otlp-source-proposal.md) before treating a rule as healthy.

[Public setup evidence](https://github.com/alanlima/pawlocal/issues/333#issuecomment-6385622035) records completed exact `oncall-production` values:

| Variable | Readback |
|---|---|
| `PAWLOCAL_GRAFANA_URL` | `https://alanlima.grafana.net` |
| `VITE_API_BASE_URL` | `https://api.alanlima.cloud/api/v1` |
| `PAWLOCAL_PUBLIC_BASE_URL` | `https://pawlocal.alanlima.cloud` |

`PAWLOCAL_ONCALL_ENABLED` remains absent intentionally. Preserve the existing model profile, query credential and production-read approval; do not copy development model settings or extract secret values.

## Reviewable public rule selection

| Field | Proposed selection |
|---|---|
| Stack | `https://alanlima.grafana.net` |
| Production folder | Existing `pawlocal-production` folder, exact UID to be read back |
| Production rule UID | `pawlocal-production-search-detail` |
| Production title | `pawlocal-production-search-detail-failure` |
| Labels | `environment=production`, `service=pawlocal-api` |
| Metrics datasource | UID `grafanacloud-prom`, name `grafanacloud-alanlima-prom` |
| Condition, reducer, threshold, evaluation interval, pending period, NoData/Error handling | Preserve the complete reviewed development rule's semantics; public definition readback is still required |
| Routing | Preserve current policies/contact points; no new production-origin model intake |

Before any rule write, inspect the complete existing DEV rule, folder/group identities and proposed PROD UID. Reject ambiguous matches, unexpected existing ownership or foreign collisions; never silently adopt/overwrite a rule or group. Record a full public before/after payload diff for review. The proposed DEV edit changes only the query; the PROD rule uses identical reviewed condition semantics with production selectors. Missing exact timing/routing fields make this a setup plan, not an executable payload.

For production, the proposed query is:

```promql
sum(rate(pawlocal_api_requests_total{environment="production",service="pawlocal-api",route=~"/api/v1/places.*",status_class="5xx"}[2m]))
or
(0 * sum(rate(pawlocal_api_requests_total{environment="production",service="pawlocal-api",route=~"/api/v1/places.*"}[2m])))
```

The DEV query changes only the environment selector. Confirm the route matcher against actual DEV public readback before mutation. Both sums discard labels, so the left side preserves a positive error rate while the right side yields zero only when matching traffic exists. Do not use unconditional `or vector(0)`: absent, stale or insufficient telemetry must remain NoData.

## Credential-free semantic proof

The [companion fixture](../../tests/observability/production-recovery-query.test.yml) uses official Prometheus `promtool` 3.5.0, matching the repository's Prometheus image version. It proves seven cases: healthy matching traffic with no error series gives zero; observed errors retain 0.1/s; absent production despite development traffic remains empty; one sample remains empty; stale traffic remains empty; another service or route cannot synthesize zero. This proves query semantics, not live production ingestion or query-token permissions.

Run the fixture with a verified official 3.5.0 binary:

```sh
promtool test rules tests/observability/production-recovery-query.test.yml
```

## Remaining live gates and ownership

1. Obtain the explicit #241 architecture decision, reviewed implementation, fresh metadata-only state ownership/collision inventory, protected-input mechanism approval and separately approved exact Terraform plans. No direct AWS mutation, import, legacy adoption or String fallback is allowed.
2. Verify successful production export and correctly labelled API/dependency series after normal healthy requests. Do not induce a production fault. Missing production telemetry must stop readiness.
3. Verify the actual Grafana account plan and account-wide managed-rule usage before adding a rule. [Published Grafana documentation](https://grafana.com/docs/grafana-cloud/observe-and-act/alert-and-measure-reliability/alerting/alerting-rules/create-grafana-managed-rule/) lists a Free allowance of 500 managed rules; this is not proof of available live quota. No new subscription, Synthetic Monitoring check or billable AWS resource is selected by the public rule plan.
4. Review exact public rule definitions and use only an already authorized operator execution context. Existing `production_setup.py` owns folder/Faro setup and `experience.py` is development-specific; neither is an approved production API-rule owner. Repository absence does not prove live ownership. Record the selected rule lifecycle owner before creating or changing anything; a new helper/authority requires its own reviewed implementation.
5. Read back exact labels, datasource, conditions/timing, unpaused state, fresh evaluation and no error. Verify trusted `configured_rule("production")` with the actual runtime query credential; a GitHub secret name or owner's UI session does not prove that credential works.
6. Only after readiness succeeds, complete the enable flag under the existing initial-setup authorization. The next incident still requires authentic candidate checks, exact-release DEV/PROD verification and 720 seconds of recovery observation. #229/#231 remain open until actual end-to-end acceptance.

The approved AI budget is separate from AWS secret setup and Grafana account quota. No paid incident, live monitoring write or AWS change is performed by this proposal.
