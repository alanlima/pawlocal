import io
import json
import logging

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pawlocal.config import settings
from pawlocal.observability import _SafeJsonFormatter


def test_browser_trace_context_reaches_database_and_safe_logs(client, monkeypatch):
    from pawlocal import observability

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)

    api_logger = logging.getLogger("pawlocal.api")
    console = next(
        handler
        for handler in api_logger.handlers
        if getattr(handler, "_pawlocal_json", False)
    )
    original_stream = console.stream
    captured = io.StringIO()
    console.setStream(captured)
    try:
        response = client[0].get(
            "/api/v1/places?q=private-search-term",
            headers={
                "traceparent": "00-11111111111111111111111111111111-2222222222222222-01"
            },
        )
    finally:
        console.setStream(original_stream)

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    api_span = next(span for span in spans if span.kind.name == "SERVER")
    application_span = next(span for span in spans if span.name == "places.search")
    database_span = next(span for span in spans if span.name == "db.query")
    assert f"{api_span.context.trace_id:032x}" == "11111111111111111111111111111111"
    assert api_span.parent.span_id == int("2222222222222222", 16)
    assert application_span.parent.span_id == api_span.context.span_id
    assert database_span.parent.span_id == application_span.context.span_id
    lines = [json.loads(line) for line in captured.getvalue().splitlines()]
    assert {line["severity"] for line in lines} == {"DEBUG", "INFO"}
    assert all(line["trace_id"] == "1" * 32 for line in lines)
    assert "private-search-term" not in captured.getvalue()


def test_synthetic_database_failure_is_correlated_and_bounded(client, monkeypatch):
    from pawlocal import observability

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)
    monkeypatch.setattr(settings, "demo_faults_enabled", True)

    response = client[0].get(
        "/api/v1/places",
        headers={
            "traceparent": "00-33333333333333333333333333333333-4444444444444444-01",
            "x-pawlocal-demo-failure": "database",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "synthetic_database_unavailable"
    spans = exporter.get_finished_spans()
    api_span = next(span for span in spans if span.kind.name == "SERVER")
    database_span = next(span for span in spans if span.name == "db.connection")
    assert database_span.parent.span_id == api_span.context.span_id
    assert database_span.status.status_code.name == "ERROR"
    assert database_span.attributes["error.code"] == "synthetic_database_unavailable"


def test_synthetic_api_failure_is_a_safe_correlated_error(client, monkeypatch):
    from pawlocal import observability

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)
    monkeypatch.setattr(settings, "demo_faults_enabled", True)

    response = client[0].get(
        "/api/v1/places",
        headers={
            "traceparent": "00-55555555555555555555555555555555-6666666666666666-01",
            "x-pawlocal-demo-failure": "api",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "synthetic_api_unavailable"
    api_span = next(
        span for span in exporter.get_finished_spans() if span.kind.name == "SERVER"
    )
    assert api_span.status.status_code.name == "ERROR"
    assert api_span.attributes["error.code"] == "synthetic_api_unavailable"


def test_structured_formatter_omits_unapproved_fields():
    record = logging.LogRecord(
        "pawlocal.api", logging.INFO, "api.py", 1, "API request completed", (), None
    )
    record.event_code = "api.request.completed"
    record.trace_id = "a" * 32
    record.query = "private text"
    record.authorization = "Bearer private-token"
    encoded = _SafeJsonFormatter().format(record)
    assert "api.request.completed" in encoded
    assert "private text" not in encoded
    assert "private-token" not in encoded
