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
                "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
                "tracestate": "vendor=private-tracestate-sentinel",
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
    assert all(not span.context.trace_state.to_header() for span in spans)
    assert all("url.query" not in span.attributes for span in spans)
    exported = "\n".join(span.to_json() for span in spans)
    assert "private-search-term" not in exported
    assert "private-tracestate-sentinel" not in exported
    lines = [json.loads(line) for line in captured.getvalue().splitlines()]
    assert {line["severity"] for line in lines} == {"DEBUG", "INFO"}
    assert all(line["trace_id"] == "1" * 32 for line in lines)
    assert "private-search-term" not in captured.getvalue()


def test_detail_request_context_parents_api_application_and_database(
    client, monkeypatch
):
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


def test_unhandled_api_error_keeps_specific_trace_and_log_code(client, monkeypatch):
    from pawlocal import observability
    from pawlocal.api import routes
    from pawlocal.main import app

    class DatabaseConnectError(RuntimeError):
        sqlstate = "08001"

    class BrokenQueries:
        def search(self, **_filters):
            raise DatabaseConnectError(
                "private backend failure detail; SELECT * FROM private_table"
            )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)
    app.dependency_overrides[routes.get_place_queries] = lambda: BrokenQueries()

    api_logger = logging.getLogger("pawlocal.api")
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setFormatter(_SafeJsonFormatter())
    api_logger.addHandler(handler)
    try:
        response = client[0].get("/api/v1/places")
    finally:
        api_logger.removeHandler(handler)

    assert response.status_code == 500
    response_json = response.json()
    assert response_json == {
        "code": "internal_error",
        "message": "Request could not be completed",
    }
    assert "private backend failure detail" not in json.dumps(response_json)
    assert "SELECT * FROM private_table" not in json.dumps(response_json)
    span = next(
        span for span in exporter.get_finished_spans() if span.kind.name == "SERVER"
    )
    assert span.status.status_code.name == "ERROR"
    assert span.attributes["error.code"] == "unhandled_api_error"
    completed_log = next(
        json.loads(line)
        for line in captured.getvalue().splitlines()
        if "API request completed" in line
    )
    assert completed_log["error_code"] == "unhandled_api_error"
    assert completed_log["exception_class"] == "DatabaseConnectError"
    assert completed_log["database_error_code"] == "08001"
    assert "private backend failure detail" not in captured.getvalue()
    assert "SELECT * FROM private_table" not in captured.getvalue()


def test_unhandled_api_error_logs_nested_missing_credentials_class_safely(client):
    import psycopg
    from botocore.exceptions import NoCredentialsError
    from sqlalchemy.exc import OperationalError

    from pawlocal.api import routes
    from pawlocal.main import app

    class BrokenQueries:
        def search(self, **_filters):
            try:
                raise NoCredentialsError()
            except NoCredentialsError as credential_error:
                try:
                    raise RuntimeError(
                        "Failed to generate authentication token: private sentinel"
                    ) from credential_error
                except RuntimeError as token_error:
                    try:
                        raise psycopg.OperationalError(
                            "private driver detail"
                        ) from token_error
                    except psycopg.OperationalError as driver_error:
                        raise OperationalError(
                            "private SQL and parameters",
                            None,
                            driver_error,
                            hide_parameters=True,
                        )

    app.dependency_overrides[routes.get_place_queries] = lambda: BrokenQueries()
    api_logger = logging.getLogger("pawlocal.api")
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setFormatter(_SafeJsonFormatter())
    api_logger.addHandler(handler)
    try:
        response = client[0].get("/api/v1/places")
    finally:
        api_logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    completed_log = next(
        json.loads(line)
        for line in captured.getvalue().splitlines()
        if "API request completed" in line
    )
    assert completed_log["exception_class"] == "OperationalError"
    assert completed_log["exception_chain"] == [
        "OperationalError",
        "RuntimeError",
        "NoCredentialsError",
    ]
    assert "private sentinel" not in captured.getvalue()
    assert "Unable to locate credentials" not in captured.getvalue()
    assert "private" not in json.dumps(response.json())


def test_suppressed_exception_context_is_not_emitted_to_json_log():
    from pawlocal.observability import safe_exception_log_fields

    class SuppressedProviderError(Exception):
        pass

    try:
        raise SuppressedProviderError("private suppressed detail")
    except SuppressedProviderError:
        try:
            raise RuntimeError("sanitized provider failure") from None
        except RuntimeError as translated_error:
            fields = safe_exception_log_fields(translated_error)

    record = logging.LogRecord(
        "pawlocal.api", logging.ERROR, "main.py", 1, "API request completed", (), None
    )
    for key, value in fields.items():
        setattr(record, key, value)
    encoded_log = _SafeJsonFormatter().format(record)

    assert fields == {"exception_class": "RuntimeError", "exception_chain": []}
    assert "SuppressedProviderError" not in encoded_log
    assert "private suppressed detail" not in encoded_log


def test_exception_log_fields_reject_non_sqlstate_values():
    from pawlocal.observability import safe_exception_log_fields

    class ErrorWithUnsafeCode(RuntimeError):
        sqlstate = "08001 private-value"
        pgcode = "not-a-sqlstate"

    fields = safe_exception_log_fields(ErrorWithUnsafeCode("private message"))

    assert fields == {
        "exception_class": "ErrorWithUnsafeCode",
        "exception_chain": [],
    }


@pytest.mark.parametrize(
    ("driver_pgcode", "expected_fields"),
    [
        (
            "08006",
            {
                "exception_class": "OperationalError",
                "exception_chain": ["DriverError"],
                "database_error_code": "08006",
            },
        ),
        (
            "08006-private",
            {
                "exception_class": "OperationalError",
                "exception_chain": ["DriverError"],
            },
        ),
    ],
)
def test_exception_log_fields_read_only_validated_sqlalchemy_orig_pgcode(
    driver_pgcode, expected_fields
):
    from sqlalchemy.exc import OperationalError

    class DriverError(Exception):
        pgcode = driver_pgcode

    wrapped = OperationalError(
        "statement text must not be logged",
        None,
        DriverError("private driver message"),
        hide_parameters=True,
    )

    from pawlocal.observability import safe_exception_log_fields

    assert safe_exception_log_fields(wrapped) == expected_fields


def test_exception_log_fields_capture_innermost_provider_error_without_text():
    from botocore.exceptions import NoCredentialsError
    from sqlalchemy.exc import OperationalError

    from pawlocal.observability import safe_exception_log_fields

    class DriverConnectionError(Exception):
        pass

    try:
        try:
            raise NoCredentialsError()
        except NoCredentialsError as credential_error:
            raise RuntimeError(
                "private token generation failure sentinel"
            ) from credential_error
    except RuntimeError as connector_error:
        try:
            raise DriverConnectionError(
                "private database endpoint and token sentinel"
            ) from connector_error
        except DriverConnectionError as driver_error:
            wrapped = OperationalError(
                "private SQL and bind value sentinel",
                None,
                driver_error,
                hide_parameters=True,
            )

    fields = safe_exception_log_fields(wrapped)

    assert fields == {
        "exception_class": "OperationalError",
        "exception_chain": [
            "DriverConnectionError",
            "RuntimeError",
            "NoCredentialsError",
        ],
    }
    encoded = json.dumps(fields)
    assert "private" not in encoded
    assert "sentinel" not in encoded


def test_psycopg_connection_error_logs_bounded_os_code_without_sqlstate():
    import psycopg
    from sqlalchemy.exc import OperationalError

    from pawlocal.observability import safe_exception_log_fields

    try:
        raise ConnectionRefusedError(10061, "private endpoint sentinel")
    except ConnectionRefusedError as socket_error:
        try:
            raise psycopg.OperationalError("private driver detail") from socket_error
        except psycopg.OperationalError as driver_error:
            wrapped = OperationalError(
                "private SQL and parameters",
                None,
                driver_error,
                hide_parameters=True,
            )

    fields = safe_exception_log_fields(wrapped)

    assert fields == {
        "exception_class": "OperationalError",
        "exception_chain": ["OperationalError", "ConnectionRefusedError"],
        "os_error_number": 10061,
    }
    encoded = json.dumps(fields)
    assert "private" not in encoded
    assert "sentinel" not in encoded


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

    span = next(
        span for span in exporter.get_finished_spans() if span.name == "places.search"
    )
    assert span.status.status_code.name == "ERROR"
    assert span.attributes["error.code"] == "application_operation_failed"
    error_attributes = {
        key for key in span.attributes if key.startswith(("error.", "exception."))
    }
    assert error_attributes == {"error.code"}
    assert not span.events
    encoded = span.to_json()
    assert "application-private-sentinel" not in encoded
    assert "exception.message" not in encoded
    assert "exception.stacktrace" not in encoded
    assert "exception.type" not in encoded
    assert "event.exception" not in encoded


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("add_favourite", "favourite_place_unavailable"),
        ("contribute", "contribution_place_unavailable"),
        ("report", "report_target_unavailable"),
    ],
)
def test_rejected_community_operations_mark_bounded_error_outcomes(
    monkeypatch, operation, expected_code
):
    from pawlocal import observability
    from pawlocal.application.community import CommunityCommands

    class RejectedRepository:
        def add_favourite(self, _subject, _place_id):
            return False

        def submit_contribution(self, _subject, _values):
            return None

        def submit_report(self, _subject, _values):
            return False

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability.trace, "get_tracer", provider.get_tracer)
    commands = CommunityCommands(RejectedRepository())

    if operation == "add_favourite":
        result = commands.add_favourite("private-subject", "private-place-id")
    else:
        values = {"kind": "tip", "target_type": "place"}
        result = getattr(commands, operation)("private-subject", values)

    assert result is (None if operation == "contribute" else False)
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code.name == "ERROR"
    assert span.status.description == expected_code
    assert span.attributes["pawlocal.outcome"] == "rejected"
    assert span.attributes["error.code"] == expected_code
    assert "private-subject" not in span.to_json()
    assert "private-place-id" not in span.to_json()
    assert not span.events


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
