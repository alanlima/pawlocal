import base64
import logging
from types import SimpleNamespace

import pytest
import requests
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    TraceFlags,
    set_span_in_context,
)

from pawlocal import cloud_telemetry as cloud

SENTINEL = "private-runtime-token-sentinel"
ROLE = "arn:aws:iam::111111111111:role/pawlocal-development-dsql-runtime"


class Store:
    def __init__(self):
        self.calls = []
        self.value = SENTINEL
        self.failure = False

    def get_parameter(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise RuntimeError(SENTINEL)
        return {"Parameter": {"Type": "SecureString", "Value": self.value}}


def test_exact_runtime_key_short_cache_rotation_and_failure_no_stale_fallback():
    store = Store()
    now = [0]
    auth = cloud.RefreshingSsmAuth(
        "development", "123", ROLE, lambda _: store, lambda: now[0], 60
    )
    req = requests.Request("POST", "https://otlp.example.net").prepare()
    auth(req)
    assert store.calls == [
        {
            "Name": "/pawlocal/development/secrets/grafana/otlp-token",
            "WithDecryption": True,
        }
    ]
    assert (
        req.headers["Authorization"]
        == "Basic " + base64.b64encode(f"123:{SENTINEL}".encode()).decode()
    )
    store.value = "rotated-synthetic-token"
    auth(req)
    assert len(store.calls) == 1
    now[0] = 61
    auth(req)
    assert len(store.calls) == 2
    assert (
        base64.b64decode(req.headers["Authorization"].split()[1]).decode()
        == "123:rotated-synthetic-token"
    )
    now[0] = 122
    store.failure = True
    with pytest.raises(
        requests.exceptions.RequestException, match="Telemetry credential unavailable"
    ) as error:
        auth(req)
    assert SENTINEL not in str(error.value)
    assert auth._value is None


@pytest.mark.parametrize(
    "env,role,instance",
    [("foreign", ROLE, "1"), ("production", ROLE, "1"), ("development", ROLE, "bad")],
)
def test_runtime_identity_mismatch_never_contacts_aws(env, role, instance):
    with pytest.raises(ValueError):
        cloud.RefreshingSsmAuth(
            env, instance, role, lambda _: pytest.fail("must not fetch")
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://host/otlp",
        "https://user:token@stack.grafana.net/otlp",
        "https://host/otlp",
        "https://gateway.grafana.net/otlp?token=secret",
    ],
)
def test_gateway_validation(url):
    with pytest.raises(ValueError):
        cloud.endpoint(url)


@pytest.mark.parametrize(
    "parameter_name",
    ["", "/pawlocal/development/secrets/grafana/otlp-token-v1"],
)
def test_cloud_export_is_source_redacted_correlated_and_async(
    monkeypatch, parameter_name
):
    store = Store()
    monkeypatch.setattr(cloud, "ssm_client", lambda _: store)
    prepared = []

    def send(self, request, **kwargs):
        prepared.append(request)
        response = requests.Response()
        response.status_code = 200
        response._content = b""
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    settings = SimpleNamespace(
        cloud_otlp_endpoint="https://gateway.grafana.net/otlp",
        release_environment="development",
        grafana_otlp_instance_id="123",
        grafana_otlp_token_parameter_name=parameter_name,
        dsql_assume_role_arn=ROLE,
        release_image_digest="sha256:" + "a" * 64,
    )
    traces, logs, meters, handler = cloud.configure(settings)
    assert not store.calls  # no credential lookup in configuration/request path
    with traces.get_tracer("test").start_as_current_span(
        "db.query",
        context=set_span_in_context(
            NonRecordingSpan(SpanContext(1, 1, False, TraceFlags(1)))
        ),
        kind=SpanKind.CLIENT,
        attributes={
            "db.system": "auroradsql",
            "http.request.method": "PRIVATE_METHOD_SENTINEL",
            "db.statement": "private-query-sentinel",
            "db.query.text": "private-query-sentinel",
        },
    ) as span:
        record = logging.makeLogRecord(
            {
                "msg": "private-driver-sentinel",
                "levelno": logging.ERROR,
                "levelname": "ERROR",
                "event_code": "api.request.completed",
                "operation": "/api/v1/places",
                "database_pgconn_error_message": "private-driver-sentinel",
                "trace_id": format(span.get_span_context().trace_id, "032x"),
            }
        )
        handler.emit(record)
    cloud.record_request("/api/v1/places", "GET", 200, 0.01)
    cloud.record_dependency("auroradsql", 0.01, False)
    traces.force_flush(timeout_millis=3000)
    logs.force_flush(timeout_millis=3000)
    meters.force_flush(timeout_millis=3000)
    try:
        assert store.calls
        assert {call["Name"] for call in store.calls} == {
            parameter_name or "/pawlocal/development/secrets/grafana/otlp-token"
        }
        bodies = b"".join(r.body for r in prepared)
        for forbidden in (
            b"PRIVATE_METHOD_SENTINEL",
            b"private-query-sentinel",
            b"private-driver-sentinel",
            SENTINEL.encode(),
        ):
            assert forbidden not in bodies
        for required in (
            b"pawlocal_api_requests",
            b"pawlocal_dependency_duration",
            b"environment",
            b"release",
            b"trace_id",
        ):
            assert required in bodies
        assert {r.url.rsplit("/", 1)[-1] for r in prepared} == {
            "logs",
            "traces",
            "metrics",
        }
        assert all("Authorization" in r.headers for r in prepared)
    finally:
        traces.shutdown()
        logs.shutdown()
        meters.shutdown()


def test_disabled_cloud_setup_skips_credentials(monkeypatch):
    from pawlocal import observability
    from pawlocal.config import settings

    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(settings, "telemetry_enabled", False)
    monkeypatch.setattr(
        cloud,
        "configure",
        lambda _: pytest.fail("disabled must not configure exporters"),
    )
    observability.configure_observability()


def test_credential_outage_and_exporter_failure_leave_api_usable(client, monkeypatch):
    from pawlocal import observability

    store = Store()
    store.failure = True
    monkeypatch.setattr(cloud, "ssm_client", lambda _: store)
    settings = SimpleNamespace(
        cloud_otlp_endpoint="https://gateway.grafana.net/otlp",
        release_environment="development",
        grafana_otlp_instance_id="123",
        grafana_otlp_token_parameter_name="/pawlocal/development/secrets/grafana/otlp-token-v1",
        dsql_assume_role_arn=ROLE,
        release_image_digest="sha256:" + "a" * 64,
    )
    traces, logs, meters, handler = cloud.configure(settings)
    monkeypatch.setattr(observability.trace, "get_tracer", traces.get_tracer)
    logger = logging.getLogger("pawlocal.api")
    logger.addHandler(handler)
    try:
        response = client[0].get("/api/v1/places?q=private-query-sentinel")
        assert response.status_code == 200
        traces.force_flush(timeout_millis=3000)
        logs.force_flush(timeout_millis=3000)
        assert store.calls
        assert {call["Name"] for call in store.calls} == {
            settings.grafana_otlp_token_parameter_name
        }
        assert client[0].get("/health").status_code == 200
        monkeypatch.setattr(
            cloud.ObservedSession,
            "post",
            lambda *a, **k: (_ for _ in ()).throw(
                RuntimeError("synthetic exporter fault")
            ),
        )
        assert client[0].get("/api/v1/places").status_code == 200
        traces.force_flush(timeout_millis=3000)
        logs.force_flush(timeout_millis=3000)
    finally:
        logger.removeHandler(handler)
        traces.shutdown()
        logs.shutdown()
        meters.shutdown()


def test_cloud_sampling_is_explicit_parent_based_and_ten_percent():
    from opentelemetry.sdk.trace.sampling import Decision

    sampler = cloud.cloud_sampler()
    assert (
        sampler.should_sample(None, 1, "query").decision == Decision.RECORD_AND_SAMPLE
    )
    assert (
        sampler.should_sample(None, (1 << 128) - 1, "query").decision == Decision.DROP
    )
    sampled = set_span_in_context(
        NonRecordingSpan(SpanContext(1, 1, True, TraceFlags(1)))
    )
    unsampled = set_span_in_context(
        NonRecordingSpan(SpanContext(1, 1, True, TraceFlags(0)))
    )
    assert (
        sampler.should_sample(sampled, (1 << 128) - 1, "query").decision
        == Decision.RECORD_AND_SAMPLE
    )
    assert sampler.should_sample(unsampled, 1, "query").decision == Decision.DROP


def test_metric_sdk_fault_does_not_change_api_response(client, monkeypatch):
    class BrokenCounter:
        def add(self, *_args):
            raise RuntimeError("synthetic instrument failure")

    monkeypatch.setattr(cloud, "_requests", BrokenCounter())
    monkeypatch.setattr(cloud, "_dependencies", BrokenCounter())
    cloud.record_dependency("aurora_dsql", 0.1, False)
    assert client[0].get("/api/v1/places").status_code == 200


def test_cloud_logging_sdk_failure_preserves_api_success_and_error(client, monkeypatch):
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler

    provider = LoggerProvider(shutdown_on_exit=False)
    handler = cloud.SafeCloudHandler(logger_provider=provider)
    logger = logging.getLogger("pawlocal.api")
    logger.addHandler(handler)
    monkeypatch.setattr(
        LoggingHandler, "emit", lambda *_: (_ for _ in ()).throw(RuntimeError(SENTINEL))
    )
    try:
        assert client[0].get("/api/v1/places").status_code == 200
        assert client[0].get("/api/v1/unknown-endpoint").status_code == 404
    finally:
        logger.removeHandler(handler)
        provider.shutdown()


@pytest.mark.parametrize("failure", [None, "api", "database"])
@pytest.mark.parametrize(
    "path,template,normal_status",
    [
        ("/api/v1/places?q=private-search-sentinel", "/api/v1/places", 200),
        (
            "/api/v1/places/11111111-2222-3333-4444-555555555555",
            "/api/v1/places/{place_id}",
            404,
        ),
    ],
)
def test_request_records_one_request_and_latency_with_safe_route(
    client, monkeypatch, failure, path, template, normal_status
):
    import json

    from pawlocal.config import settings

    class Instrument:
        def __init__(self):
            self.calls = []

        def add(self, value, attributes):
            self.calls.append((value, attributes))

        def record(self, value, attributes):
            self.calls.append((value, attributes))

    requests, durations = Instrument(), Instrument()
    monkeypatch.setattr(settings, "demo_faults_enabled", True)
    monkeypatch.setattr(cloud, "_requests", requests)
    monkeypatch.setattr(cloud, "_duration", durations)
    response = client[0].get(
        path, headers={"x-pawlocal-demo-failure": failure} if failure else {}
    )
    assert response.status_code == (503 if failure else normal_status)
    assert len(requests.calls) == len(durations.calls) == 1
    count, labels = requests.calls[0]
    assert count == 1
    assert labels["route"] == template
    assert labels["method"] == "GET"
    assert labels["status_class"] == f"{response.status_code // 100}xx"
    assert labels["outcome"] == ("success" if response.status_code < 400 else "error")
    assert durations.calls[0][0] >= 0
    assert durations.calls[0][1] == labels
    exported = json.dumps([requests.calls, durations.calls])
    assert "private-search-sentinel" not in exported
    assert "11111111-2222-3333-4444-555555555555" not in exported


@pytest.mark.parametrize("environment", ["development", "production"])
def test_explicit_canonical_source_and_default_are_identical(environment):
    canonical = f"/pawlocal/{environment}/secrets/grafana/otlp-token"
    role = f"arn:aws:iam::111111111111:role/pawlocal-{environment}-dsql-runtime"
    for selection in ("", canonical):
        auth = cloud.RefreshingSsmAuth(
            environment, "123", role, parameter_name=selection
        )
        assert auth.path == canonical


@pytest.mark.parametrize(
    "environment,selection",
    [
        ("development", "/pawlocal/production/secrets/grafana/otlp-token"),
        ("production", "/pawlocal/development/secrets/grafana/otlp-token-v1"),
        ("production", "/pawlocal/production/secrets/grafana/otlp-token-v1"),
        ("development", "/pawlocal/development/secrets/grafana/otlp-token-v2"),
        ("development", "/pawlocal/development/secrets/grafana/*"),
        ("development", "/pawlocal/development/secrets/grafana/../otlp-token-v1"),
        ("development", "arn:aws:ssm:ap-southeast-2:111111111111:parameter/foreign"),
        ("development", " /pawlocal/development/secrets/grafana/otlp-token-v1"),
        ("development", "/pawlocal/development/secrets/grafana/otlp-token-v1\n"),
        ("development", "/pawlocal/development/secrets/grafana/otlp-token\x00"),
        ("development", "${PAWLOCAL_OTHER_PARAMETER}"),
    ],
)
def test_unapproved_source_is_rejected_before_client_creation(environment, selection):
    role = f"arn:aws:iam::111111111111:role/pawlocal-{environment}-dsql-runtime"
    with pytest.raises(ValueError, match="approved token source"):
        cloud.RefreshingSsmAuth(
            environment,
            "123",
            role,
            lambda _: pytest.fail("invalid pointer must not create a client"),
            parameter_name=selection,
        )


@pytest.mark.parametrize(
    "response_type,value", [("String", SENTINEL), ("SecureString", "")]
)
def test_selected_versioned_source_never_falls_back_or_logs_private_failure(
    response_type, value, caplog
):
    selected = "/pawlocal/development/secrets/grafana/otlp-token-v1"
    calls = []

    class InvalidSource:
        def get_parameter(self, **kwargs):
            calls.append(kwargs)
            return {"Parameter": {"Type": response_type, "Value": value}}

    auth = cloud.RefreshingSsmAuth(
        "development", "123", ROLE, lambda _: InvalidSource(), parameter_name=selected
    )
    for _ in range(2):
        req = requests.Request("POST", "https://otlp.example.net").prepare()
        with pytest.raises(requests.exceptions.RequestException) as error:
            auth(req)
        assert SENTINEL not in str(error.value)
        assert "Authorization" not in req.headers
    assert calls == [{"Name": selected, "WithDecryption": True}] * 2
    assert SENTINEL not in caplog.text


def test_public_pointer_setting_is_loaded_from_environment(monkeypatch):
    from pawlocal.config import Settings

    selected = "/pawlocal/development/secrets/grafana/otlp-token-v1"
    monkeypatch.delenv("PAWLOCAL_GRAFANA_OTLP_TOKEN_PARAMETER_NAME", raising=False)
    assert Settings(_env_file=None).grafana_otlp_token_parameter_name == ""
    monkeypatch.setenv("PAWLOCAL_GRAFANA_OTLP_TOKEN_PARAMETER_NAME", selected)
    assert Settings(_env_file=None).grafana_otlp_token_parameter_name == selected
