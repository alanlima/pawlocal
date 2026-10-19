"""Local OpenTelemetry setup and privacy-safe backend request logging."""

import errno
import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from pawlocal.config import settings

logger = logging.getLogger("pawlocal.api")
_configured = False
_propagator = TraceContextTextMapPropagator()
_tracer_provider: TracerProvider | None = None
_logger_provider: LoggerProvider | None = None
_SAFE_EXCEPTION_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SAFE_SQLSTATE = re.compile(r"[0-9A-Z]{5}\Z")
_MAX_EXCEPTION_CHAIN_DEPTH = 5


class _SafeJsonFormatter(logging.Formatter):
    """Render only an allowlist of structured fields to container stdout."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)
            ),
            "severity": record.levelname,
            "message": record.getMessage(),
        }
        for field in (
            "event_code",
            "operation",
            "outcome",
            "http_status",
            "duration_ms",
            "trace_id",
            "span_id",
            "error_code",
            "exception_class",
            "exception_chain",
            "os_error_number",
            "database_error_code",
            "database_error_classification",
            "database_error_classification_source",
            "database_pgconn_available",
            "database_pgconn_error_message_present",
            "database_auth_needs_password",
            "database_auth_used_password",
        ):
            value = getattr(record, field, None)
            if value is not None:
                fields[field] = value
        return json.dumps(fields, separators=(",", ":"))


def configure_observability() -> None:
    global _configured, _tracer_provider, _logger_provider
    if _configured:
        return
    _configured = True

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not any(
        getattr(handler, "_pawlocal_json", False) for handler in logger.handlers
    ):
        console = logging.StreamHandler()
        console.setFormatter(_SafeJsonFormatter())
        console._pawlocal_json = True  # type: ignore[attr-defined]
        logger.addHandler(console)

    if not settings.telemetry_enabled:
        return

    endpoint = settings.otlp_endpoint.rstrip("/")
    resource = Resource.create({"service.name": "pawlocal-api"})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)
    _tracer_provider = tracer_provider

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )
    otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
    logger.addHandler(otel_handler)
    _logger_provider = logger_provider


def shutdown_observability() -> None:
    for provider in (_tracer_provider, _logger_provider):
        if provider is not None:
            provider.force_flush()
            provider.shutdown()


def extract_trace_context(headers: Any):
    carrier = {
        key: headers[key] for key in ("traceparent",) if headers.get(key) is not None
    }
    return _propagator.extract(carrier)


def current_correlation_fields(span) -> dict[str, Any]:
    span_context = span.get_span_context()
    if not span_context.is_valid:
        return {}
    return {
        "trace_id": f"{span_context.trace_id:032x}",
        "span_id": f"{span_context.span_id:016x}",
    }


def log_request(level: int, message: str, *, span, **fields: Any) -> None:
    safe_fields = {
        key: value
        for key, value in fields.items()
        if key
        in {
            "event_code",
            "operation",
            "outcome",
            "http_status",
            "duration_ms",
            "error_code",
            "exception_class",
            "exception_chain",
            "os_error_number",
            "database_error_code",
            "database_error_classification",
            "database_error_classification_source",
            "database_pgconn_available",
            "database_pgconn_error_message_present",
            "database_auth_needs_password",
            "database_auth_used_password",
        }
    }
    safe_fields.update(current_correlation_fields(span))
    logger.log(level, message, extra=safe_fields)


def safe_exception_log_fields(exc: BaseException) -> dict[str, Any]:
    """Return bounded exception identifiers without messages or traceback data.

    Database drivers often wrap an operating-system failure. Record only
    exception type names, validated SQLSTATEs, bounded OS error numbers, and a
    fixed database-error classification. Driver messages are inspected only in
    memory to map known phrases to constants; message text is never returned.
    """
    class_name = type(exc).__name__
    fields = {
        "exception_class": (
            class_name
            if _SAFE_EXCEPTION_CLASS.fullmatch(class_name)
            else "UnknownException"
        )
    }

    # SQLAlchemy wraps the DB driver exception in ``orig``; drivers may then
    # chain socket/DNS/provider exceptions via __cause__ or __context__. Follow
    # that linear chain (preferring explicit causes), and retain identities
    # only, never exception text or tracebacks.
    candidates: list[BaseException] = []
    seen: set[int] = set()
    candidate: BaseException | None = exc
    while candidate is not None and len(candidates) < _MAX_EXCEPTION_CHAIN_DEPTH:
        if id(candidate) in seen:
            break
        seen.add(id(candidate))
        candidates.append(candidate)
        original = getattr(candidate, "orig", None)
        cause = getattr(candidate, "__cause__", None)
        context = getattr(candidate, "__context__", None)
        next_candidate = original if isinstance(original, BaseException) else None
        if next_candidate is None or id(next_candidate) in seen:
            next_candidate = cause if isinstance(cause, BaseException) else None
        context_is_visible = not getattr(candidate, "__suppress_context__", False)
        if (
            next_candidate is None
            and context_is_visible
            and isinstance(context, BaseException)
        ):
            next_candidate = context
        candidate = next_candidate

    fields["exception_chain"] = [_safe_exception_class(item) for item in candidates[1:]]

    for candidate in candidates:
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str) and _SAFE_SQLSTATE.fullmatch(value.upper()):
                fields["database_error_code"] = value.upper()
                break
        if "database_error_code" in fields:
            break

    # errno is a numeric OS error identifier (for example ECONNREFUSED or
    # ETIMEDOUT); reject booleans, non-integers, and out-of-range values.
    for candidate in candidates:
        value = getattr(candidate, "errno", None)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and -(2**31) <= value < 2**31
        ):
            fields["os_error_number"] = value
            break

    database_candidates = [
        item
        for item in candidates
        if type(item).__module__.split(".", 1)[0] in {"psycopg", "psycopg2"}
    ]
    if database_candidates or any(
        _safe_exception_class(item) in {"OperationalError", "DatabaseError"}
        for item in candidates
    ):
        (
            fields["database_error_classification"],
            fields["database_error_classification_source"],
        ) = _classify_database_error(candidates, database_candidates)
        fields["database_pgconn_error_message_present"] = False
        for driver_error in database_candidates:
            pgconn = _safe_attribute(driver_error, "pgconn")
            fields["database_pgconn_available"] = pgconn is not None
            if pgconn is None:
                break
            pgconn_message = _safe_attribute(pgconn, "error_message")
            fields["database_pgconn_error_message_present"] = isinstance(
                pgconn_message, (bytes, str)
            ) and bool(pgconn_message)
            for attribute, field in (
                ("needs_password", "database_auth_needs_password"),
                ("used_password", "database_auth_used_password"),
            ):
                value = _safe_attribute(pgconn, attribute)
                if isinstance(value, bool):
                    fields[field] = value
            break
    return fields


def _safe_attribute(value: Any, name: str) -> Any:
    try:
        return getattr(value, name, None)
    except Exception:  # noqa: BLE001 - optional driver diagnostics must not mask the original failure
        return None


def _classify_database_error(
    candidates: list[BaseException], driver_candidates: list[BaseException]
) -> tuple[str, str]:
    """Map database failures to constants; never return exception text."""
    classes = {_safe_exception_class(item) for item in candidates}
    sqlstate = next(
        (
            code
            for item in candidates
            for code in (getattr(item, "sqlstate", None), getattr(item, "pgcode", None))
            if isinstance(code, str) and _SAFE_SQLSTATE.fullmatch(code.upper())
        ),
        None,
    )
    if "NoCredentialsError" in classes:
        return "credential_provider_missing", "exception_class"
    if sqlstate and sqlstate.startswith("28"):
        return "authentication_rejected", "sqlstate"
    if "gaierror" in classes:
        return "dns_resolution_failed", "exception_class"
    if classes.intersection({"CertificateError", "SSLCertVerificationError"}):
        return "tls_verification_failed", "exception_class"
    if "SSLError" in classes:
        return "tls_connection_failed", "exception_class"
    numbers = [getattr(item, "errno", None) for item in candidates]
    if errno.ECONNREFUSED in numbers:
        return "connection_refused", "os_errno"
    if errno.ETIMEDOUT in numbers or classes.intersection(
        {"TimeoutError", "ConnectionTimeout"}
    ):
        return (
            "connection_timeout",
            "os_errno" if errno.ETIMEDOUT in numbers else "exception_class",
        )

    # Driver and libpq diagnostics stay in memory. They are bounded before
    # matching and can only select fixed enum values; neither string is logged.
    diagnostic_messages: list[tuple[str, str]] = []
    for item in driver_candidates:
        args = getattr(item, "args", ())
        driver_message = args[0] if args and isinstance(args[0], str) else ""
        if driver_message:
            diagnostic_messages.append(
                ("driver_message_pattern", driver_message[:2048].lower())
            )
        pgconn = _safe_attribute(item, "pgconn")
        pgconn_message = _safe_attribute(pgconn, "error_message")
        if isinstance(pgconn_message, bytes):
            pgconn_message = pgconn_message[:2048].decode("utf-8", errors="replace")
        if isinstance(pgconn_message, str) and pgconn_message:
            diagnostic_messages.append(
                ("pgconn_error_message_pattern", pgconn_message[:2048].lower())
            )

    message_classifications: set[str] = set()
    message_sources: set[str] = set()
    for source, message in diagnostic_messages:
        matches: set[str] = set()
        if "failed to generate authentication token" in message:
            matches.add("token_generation_failed")
        if (
            "password authentication failed" in message
            or "authentication failed" in message
        ):
            matches.add("authentication_rejected")
        if "certificate verify failed" in message:
            matches.add("tls_verification_failed")
        elif "tls handshake" in message:
            matches.add("tls_connection_failed")
        if "connection timed out" in message or "connection timeout expired" in message:
            matches.add("connection_timeout")
        if "connection refused" in message:
            matches.add("connection_refused")
        if (
            "could not translate host name" in message
            or "name or service not known" in message
        ):
            matches.add("dns_resolution_failed")
        if matches:
            message_classifications.update(matches)
            message_sources.add(source)
    if len(message_classifications) == 1:
        source = (
            "pgconn_error_message_pattern"
            if "pgconn_error_message_pattern" in message_sources
            else "driver_message_pattern"
        )
        return next(iter(message_classifications)), source
    if len(message_classifications) > 1:
        return "connection_failure_unknown", "ambiguous_driver_message"
    return "connection_failure_unknown", "fallback"


def _safe_exception_class(exc: BaseException) -> str:
    class_name = type(exc).__name__
    return (
        class_name
        if _SAFE_EXCEPTION_CLASS.fullmatch(class_name)
        else "UnknownException"
    )


def create_api_span(name: str, context):
    return trace.get_tracer("pawlocal.api").start_as_current_span(
        name,
        context=context,
        kind=SpanKind.SERVER,
        record_exception=False,
        set_status_on_exception=False,
    )


@contextmanager
def application_span(name: str, attributes: dict[str, Any]) -> Iterator[Span]:
    """Create a safe application span and mark failures without recording exceptions."""
    with trace.get_tracer("pawlocal.application").start_as_current_span(
        name,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception:
            mark_failed(span, "application_operation_failed")
            raise


def mark_failed(span, stable_code: str) -> None:
    span.set_status(Status(StatusCode.ERROR, stable_code))
    span.set_attribute("error.code", stable_code)


def mark_rejected(span, stable_code: str) -> None:
    """Mark an expected domain rejection with bounded, non-sensitive fields."""
    span.set_status(Status(StatusCode.ERROR, stable_code))
    span.set_attribute("pawlocal.outcome", "rejected")
    span.set_attribute("error.code", stable_code)


def synthetic_database_failure(span) -> None:
    """Create a bounded child span that models a local database outage."""
    with trace.get_tracer("pawlocal.database").start_as_current_span(
        "db.connection",
        kind=SpanKind.CLIENT,
        attributes={"db.system": "postgresql", "pawlocal.synthetic": True},
        record_exception=False,
        set_status_on_exception=False,
    ) as database_span:
        mark_failed(database_span, "synthetic_database_unavailable")
