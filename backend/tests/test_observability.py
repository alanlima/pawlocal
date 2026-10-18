import io
import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

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
    database_span = next(
        span
        for span in spans
        if span.name == "db.query"
        and span.context.trace_id == api_span.context.trace_id
    )
    assert f"{api_span.context.trace_id:032x}" == "11111111111111111111111111111111"
    assert api_span.parent.span_id == int("2222222222222222", 16)
    assert application_span.parent.span_id == api_span.context.span_id
    assert database_span.parent.span_id == application_span.context.span_id
    assert all("url.query" not in span.attributes for span in spans)
    assert "private-search-term" not in "\n".join(span.to_json() for span in spans)
    lines = [json.loads(line) for line in captured.getvalue().splitlines()]
    assert {line["severity"] for line in lines} == {"DEBUG", "INFO"}
    assert all(line["trace_id"] == "1" * 32 for line in lines)
    assert "private-search-term" not in captured.getvalue()


def test_detail_request_context_parents_api_application_and_database(client, monkeypatch):
    from uuid import UUID

    from pawlocal import observability
    from pawlocal.infrastructure.models import PlaceRecord

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)
    place_id = UUID("00000000-0000-4000-8000-000000000992")
    with client[1]() as session:
        session.add(
            PlaceRecord(
                id=place_id,
                name="Synthetic Trace Fixture",
                category="dog_park",
                area="Brisbane",
                facilities=[],
                is_published=True,
            )
        )
        session.commit()

    response = client[0].get(
        f"/api/v1/places/{place_id}",
        headers={
            "traceparent": "00-77777777777777777777777777777777-8888888888888888-01"
        },
    )
    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    api_span = next(span for span in spans if span.kind.name == "SERVER")
    application_span = next(span for span in spans if span.name == "places.get")
    database_span = next(
        span
        for span in spans
        if span.name == "db.query"
        and span.context.trace_id == api_span.context.trace_id
    )
    assert f"{api_span.context.trace_id:032x}" == "7" * 32
    assert api_span.parent.span_id == int("8888888888888888", 16)
    assert application_span.parent.span_id == api_span.context.span_id
    assert database_span.parent.span_id == application_span.context.span_id


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


def test_failed_sql_query_does_not_export_exception_details(monkeypatch):
    from pawlocal import observability

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sentinel = "privacy-sentinel-user-value"
    try:
        with engine.connect() as connection, pytest.raises(OperationalError):
            connection.exec_driver_sql(f"SELECT * FROM {sentinel}")
        spans = exporter.get_finished_spans()
        database_span = next(span for span in spans if span.name == "db.query")
        assert database_span.status.status_code.name == "ERROR"
        assert database_span.attributes["error.code"] == "database_operation_failed"
        encoded = "\n".join(span.to_json() for span in spans)
        assert sentinel not in encoded
        assert "exception.message" not in encoded
        assert "exception.stacktrace" not in encoded
        assert "exception.type" not in encoded
        assert "event.exception" not in encoded
        assert all(not span.events for span in spans)
    finally:
        engine.dispose()


def test_application_failure_sets_only_stable_error_code(monkeypatch):
    from sqlalchemy.exc import OperationalError

    from pawlocal import observability
    from pawlocal.application.places import PlaceQueries

    class BrokenRepository:
        def search(self, **_filters):
            sentinel = "application-private-sentinel"
            raise OperationalError(
                f"SELECT '{sentinel}'",
                {"value": sentinel},
                RuntimeError(sentinel),
            )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)

    with pytest.raises(OperationalError):
        PlaceQueries(BrokenRepository()).search()

    span = next(span for span in exporter.get_finished_spans() if span.name == "places.search")
    assert span.status.status_code.name == "ERROR"
    assert span.attributes["error.code"] == "application_operation_failed"
    error_attributes = {
        key
        for key in span.attributes
        if key.startswith(("error.", "exception."))
    }
    assert error_attributes == {"error.code"}
    assert not span.events
    encoded = span.to_json()
    assert "application-private-sentinel" not in encoded
    assert "exception.message" not in encoded
    assert "exception.stacktrace" not in encoded
    assert "exception.type" not in encoded
    assert "event.exception" not in encoded


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


def test_backend_demo_faults_use_the_explicit_backend_setting(monkeypatch):
    from pawlocal.config import Settings

    monkeypatch.setenv("PAWLOCAL_DEMO_FAULTS_ENABLED", "true")
    monkeypatch.setenv("PAWLOCAL_DEMO_FAULTS", "false")

    assert Settings().demo_faults_enabled is True
