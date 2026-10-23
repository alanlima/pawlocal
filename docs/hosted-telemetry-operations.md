# Direct hosted telemetry operations (#225)

This change supplies disabled-by-default code and mocked verification. It does not activate the shared Grafana stack, create credentials, populate sources, change protected settings or apply infrastructure. Live G1 acceptance remains with #226 and parent #59. The current incident-loop approval policy is maintained by #239; telemetry does not select a model or grant deployment authority.

## Public configuration and release identity

The matching application state accepts optional `hosted_observability`, supplied by the matching plan Environment variable `PAWLOCAL_HOSTED_OBSERVABILITY_CONFIG`. Its exact public fields are `enabled` (defaults false), `stack_url`, `otlp_endpoint`, `otlp_instance_id`, `faro_collector_url`, and optional `kms_key_arn` for an existing matching customer key. Null publishes `/pawlocal/{environment}/config/observability/enabled=false` and grants no OTLP-secret access. A reviewed non-null object additionally publishes four public `/config/grafana/` Strings. Each public String carries project/environment/configuration-access tags required by #237. No token input, output or source resource is introduced.

The same single YAML copier synchronizes public values. The release consumer separately requires matching backend/browser mode, existing baseline public configuration, and valid Faro/OTLP bindings when enabled. Missing/inconsistent settings stop publication; stale Environment variables cannot supply a missing same-run snapshot. Disabled releases omit stale Faro bindings. A protected public object is validated before plan creation; saved-plan application uses those exact inputs.

The Lightsail runtime receives public mode, endpoint and instance identifier; `OTEL_SDK_DISABLED` is the inverse of the same mode. The frontend receives public collector URL only when enabled. Release manifests and verification evidence represent the actual boolean mode. Verification checks `/health` reports the expected configured mode and image identity, then runs the existing database/public smoke checks. A true health mode is configuration evidence, not proof the remote collector accepted a signal. Production deployment records now carry the same schema, run attempt, manifest/evidence byte digests, running image, frontend artifact and health/database evidence as development; older thin production records remain insufficient for trusted responder correlation.

## Runtime credential handoff

Only the backend export worker reads `/pawlocal/{environment}/secrets/grafana/otlp-token` as SecureString with decryption, using the existing matching DSQL runtime role. It never enters Terraform payloads/state, frontend settings or workflow outputs. Runtime IAM grants only this exact ARN. A configured customer key additionally requires exact key ARN, SSM ViaService and matching PARAMETER_ARN context in both identity and bootstrap boundary. The default AWS-managed SSM key requires no fabricated customer-key ARN. When an existing customer key is approved, set the matching public ARN both in `hosted_observability.kms_key_arn` and the protected bootstrap `TF_VAR_hosted_telemetry_kms_key_arns` environment-to-ARN map (defaults `{}`). Bootstrap validates exact account/region/environment and binds this structured input into its saved-plan checks; the actual key policy must independently permit the runtime role. No key is created or its policy changed here.

Source creation/population/rotation is still a separately reviewed lifecycle blocker under Terraform ownership and no-secret-in-state requirements. This implementation does not offer a CLI creation exception or create an empty placeholder. Query, HMAC, dispatch and publisher credentials remain separate scopes. No query-token synchronization grant is added.

Credential refresh is lazy in export workers, cached for 60 seconds and serialized. STS/SSM have one-second connection/read timeouts and one attempt. A failed refresh discards the cached credential; it does not reuse an expired token. Rotate the exact source through its approved lifecycle, wait beyond cache expiry and verify acceptance without displaying payloads. Source read, outage and rotation behavior have synthetic local tests; actual AWS/Grafana rotation remains unverified.

## Privacy, bounds and sampling

Backend logs exported to Grafana contain only fixed operational event fields, route templates, outcomes, numeric durations/status and correlation identifiers plus environment/service/release. SQL, query strings, request/response bodies, exception descriptions and driver diagnostics do not enter cloud telemetry. Operational container stdout keeps its existing diagnostic behavior. Trace export drops arbitrary events, links and status descriptions; HTTP method values normalize to a fixed set or OTHER.

Faro uses manual journey signals only: no automatic browser, page, resource, session, user, geolocation or console instrumentation. The outgoing metadata contains only the reviewed application identity; safe trace attributes use fixed value enums. Manual logs say journey_completed and carry bounded operation/outcome; measurements carry duration_ms. Traceparent propagates only to the configured API origin in hosted mode; tracestate is omitted.

Both hosted trace SDKs use parent-based sampling with a 10% root ratio. Local Compose keeps its existing always-on tracing. Backend trace/log queues hold at most 256 items, exporting batches of 64 at one-second intervals; backend metrics export every 15 seconds. Browser traces hold 100 items and batches of 20; Faro transport holds 100 with concurrency one, a two-second request timeout and one attempt. Queues are memory-only and may drop during outage/restart. SDK/export failures must not change business responses. Sampling and bounds reduce load; they do not establish a billing cap or prove the Free tier entitlement. Shared-stack privacy and actual signal permissions, ingestion limits, retention and trial-to-Free behavior still require live acceptance.

## Dashboard contract

All backend measurements explicitly include environment, service=pawlocal-api and release=verified image digest (or unknown outside a verified release). API dimensions use route template, fixed method, status_class and outcome. Dependency dimensions use dependency=aurora_dsql|postgresql, operation=query and outcome.

| Instrument | Unit / expected Prometheus family |
|---|---|
| pawlocal_api_requests | counter / pawlocal_api_requests_total |
| pawlocal_api_duration | seconds histogram / pawlocal_api_duration_seconds_* |
| pawlocal_dependency_requests | counter / pawlocal_dependency_requests_total |
| pawlocal_dependency_duration | seconds histogram / pawlocal_dependency_duration_seconds_* |
| pawlocal_telemetry_exports | counter, signal=traces|logs|metrics / *_total |
| pawlocal_telemetry_export_failures | counter, same signal values / *_total |

The exporter failure counter may be absent until a failure; absence is not proof of health. If the metrics exporter itself is unavailable, its counters cannot deliver their own failure. Native synthetic checks and explicit no-data handling remain independent evidence. Actual Grafana OTLP translation and query compatibility must be checked before G1; resource-attribute promotion is not assumed. Logs include explicit environment/service/release JSON fields. Traces use service.name, service.version and deployment.environment.name resource attributes.

## Disable and recovery

Disable via the reviewed public mode object and normal Terraform/release lifecycle, with applicable setup/apply authorization. Build and deploy matching false modes and verify health/evidence identity. Do not patch a running container or use AWS-side imperative deployment. Test collector outage while search/detail still work; verify no private payloads in captured export, then restore only the approved collector/source and inspect the correlated journey in Grafana. Actual live ingestion, no-data alerts, Free usage and recovery evidence remain outstanding.
