"""Bounded direct-cloud export. Private credentials are fetched only by export workers."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from urllib.parse import urlsplit

import requests
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Status

from pawlocal.infrastructure.query_telemetry import safe_query_template

SAFE_SPAN_FIELDS = frozenset(
    {
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "db.system",
        "db.operation.name",
        "pawlocal.operation",
        "pawlocal.outcome",
        "error.code",
    }
)
SAFE_LOG_FIELDS = frozenset(
    {
        "event_code",
        "operation",
        "outcome",
        "http_status",
        "duration_ms",
        "trace_id",
        "span_id",
        "trace_sampled",
        "error_code",
    }
)
_requests = _duration = _dependencies = _dependency_duration = None
_exports = _export_failures = None
_labels = {}


def cloud_sampler():
    return ParentBased(TraceIdRatioBased(0.1))


def endpoint(value):
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or not url.hostname.endswith(".grafana.net")
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.port is not None
        or url.path.rstrip("/") != "/otlp"
    ):
        raise ValueError(
            "Hosted OTLP requires a verified Grafana HTTPS gateway /otlp URL"
        )
    return value.rstrip("/")


def ssm_client(role_arn):
    import boto3
    from botocore.config import Config
    from botocore.session import Session

    from pawlocal.infrastructure.aws_credentials import AssumeRoleCredentialProvider

    config = Config(
        connect_timeout=1, read_timeout=1, retries={"total_max_attempts": 1}
    )

    class BoundedSource:
        def client(self, name):
            return boto3.Session().client(name, config=config)

    core = Session()
    core.get_component("credential_provider").insert_before(
        "env", AssumeRoleCredentialProvider(role_arn, BoundedSource())
    )
    return boto3.Session(botocore_session=core).client("ssm", config=config)


class RefreshingSsmAuth(requests.auth.AuthBase):
    """One exact runtime key, short in-memory TTL, no stale credential fallback."""

    def __init__(
        self,
        environment,
        instance_id,
        role_arn,
        client_factory=None,
        clock=time.monotonic,
        ttl=60,
        *,
        parameter_name="",
    ):
        if environment not in {"development", "production"} or not re.fullmatch(
            r"[0-9]{1,20}", instance_id
        ):
            raise ValueError(
                "Hosted telemetry needs a valid environment and Grafana instance"
            )
        if not re.fullmatch(
            rf"arn:aws:iam::[0-9]{{12}}:role/pawlocal-{environment}-dsql-runtime",
            role_arn,
        ):
            raise ValueError("Hosted telemetry must use the matching runtime role")
        canonical = f"/pawlocal/{environment}/secrets/grafana/otlp-token"
        allowed = {canonical}
        if environment == "development":
            allowed.add(canonical + "-v1")
        selected = canonical if parameter_name == "" else parameter_name
        if selected not in allowed:
            raise ValueError("Hosted telemetry requires an approved token source")
        self.path = selected
        self.instance_id, self.role_arn = instance_id, role_arn
        self.factory, self.clock, self.ttl = client_factory or ssm_client, clock, ttl
        self.client = None
        self._value = None
        self._expires = 0
        self._lock = threading.Lock()

    def __call__(self, request):
        with self._lock:
            if self.clock() >= self._expires:
                try:
                    if self.client is None:
                        self.client = self.factory(self.role_arn)
                    parameter = self.client.get_parameter(
                        Name=self.path, WithDecryption=True
                    )["Parameter"]
                    token = parameter.get("Value")
                    if (
                        parameter.get("Type") != "SecureString"
                        or not isinstance(token, str)
                        or not token
                        or any(c in token for c in "\r\n\x00")
                    ):
                        raise ValueError("Invalid runtime token")
                    self._value, self._expires = token, self.clock() + self.ttl
                except Exception:  # noqa: BLE001 - private SDK failures never escape exporter auth
                    self._value, self._expires = None, 0
                    raise requests.exceptions.RequestException(
                        "Telemetry credential unavailable"
                    ) from None
            raw = f"{self.instance_id}:{self._value}".encode()
            request.headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        return request


def metric_labels():
    return dict(_labels)


def record_request(route, method, status, seconds):
    if _requests is None:
        return
    fields = {
        **_labels,
        "route": route,
        "method": method
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
        else "OTHER",
        "status_class": f"{status // 100}xx",
        "outcome": "success" if status < 400 else "error",
    }
    try:
        _requests.add(1, fields)
        _duration.record(seconds, fields)
    except Exception:  # noqa: BLE001 - instrument failure must not affect business work
        # SDK failures must never affect the request or database transaction.
        return


def record_dependency(system, seconds, failed):
    if _dependencies is None:
        return
    fields = {
        **_labels,
        "dependency": "aurora_dsql" if "dsql" in system else "postgresql",
        "operation": "query",
        "outcome": "error" if failed else "success",
    }
    try:
        _dependencies.add(1, fields)
        _dependency_duration.record(seconds, fields)
    except Exception:  # noqa: BLE001 - instrument failure must not affect business work
        return


class SafeSpanExporter(OTLPSpanExporter):
    def export(self, spans):
        safe = [
            ReadableSpan(
                name=span.name
                if re.fullmatch(
                    r"(?:HTTP (?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)|[a-z]+[.][a-z_]+)",
                    span.name,
                )
                else "operation",
                context=span.context,
                parent=span.parent,
                resource=span.resource,
                attributes={
                    k: (
                        v
                        if v
                        in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
                        else "OTHER"
                    )
                    if k == "http.request.method"
                    else v
                    for k, v in span.attributes.items()
                    if k in SAFE_SPAN_FIELDS
                    or (
                        k == "db.query.text"
                        and safe_query_template(v) == v
                        and v is not None
                    )
                },
                events=(),
                links=(),
                kind=span.kind,
                status=Status(span.status.status_code),
                start_time=span.start_time,
                end_time=span.end_time,
                instrumentation_scope=span.instrumentation_scope,
            )
            for span in spans
        ]
        return super().export(safe)


class SafeCloudHandler(LoggingHandler):
    """Do not forward operational stdout or driver diagnostic payloads to cloud."""

    def emit(self, record):
        try:
            fields = {
                name: getattr(record, name)
                for name in SAFE_LOG_FIELDS
                if getattr(record, name, None) is not None
            }
            safe = logging.makeLogRecord(
                {
                    "name": "pawlocal.api",
                    "levelno": record.levelno,
                    "levelname": record.levelname,
                    "msg": json.dumps({**_labels, **fields}, separators=(",", ":")),
                    "args": (),
                }
            )
            super().emit(safe)
        except Exception:  # noqa: BLE001 - cloud logging must never fail a request
            # Do not recursively log failures through this handler.
            return


class ObservedSession(requests.Session):
    """Observe each HTTP attempt, including SDKs using request() directly."""

    def request(self, method, url, **kwargs):
        # Inherited post() delegates here too; observing both would double count.
        signal = urlsplit(url).path.rsplit("/", 1)[-1]
        labels = {
            **_labels,
            "signal": signal if signal in {"traces", "logs", "metrics"} else "unknown",
        }
        try:
            response = super().request(method, url, **kwargs)
        except Exception:
            self._record(_export_failures, labels)
            raise
        self._record(_exports, labels)
        if response.status_code >= 400:
            self._record(_export_failures, labels)
        return response

    @staticmethod
    def _record(counter, labels):
        try:
            if counter is not None:
                counter.add(1, labels)
        except Exception:  # noqa: BLE001 - observation cannot alter HTTP outcomes
            return


def configure(settings):
    global \
        _requests, \
        _duration, \
        _dependencies, \
        _dependency_duration, \
        _exports, \
        _export_failures, \
        _labels
    url = endpoint(settings.cloud_otlp_endpoint)
    auth = RefreshingSsmAuth(
        settings.release_environment,
        settings.grafana_otlp_instance_id,
        settings.dsql_assume_role_arn or "",
        parameter_name=settings.grafana_otlp_token_parameter_name,
    )
    release = (
        settings.release_image_digest
        if re.fullmatch(r"sha256:[0-9a-f]{64}", settings.release_image_digest or "")
        else "unknown"
    )
    _labels = {
        "environment": settings.release_environment,
        "service": "pawlocal-api",
        "release": release,
    }
    resource = Resource(
        {
            "service.name": "pawlocal-api",
            "service.version": release,
            "deployment.environment.name": settings.release_environment,
        }
    )

    def session():
        result = ObservedSession()
        result.auth = auth
        return result

    metric_exporter = OTLPMetricExporter(
        endpoint=url + "/v1/metrics", timeout=2, session=session()
    )
    reader = PeriodicExportingMetricReader(
        metric_exporter, export_interval_millis=15000, export_timeout_millis=2500
    )
    meters = MeterProvider(
        resource=resource, metric_readers=[reader], shutdown_on_exit=False
    )
    meter = meters.get_meter("pawlocal.api")
    _requests = meter.create_counter("pawlocal_api_requests")
    _duration = meter.create_histogram("pawlocal_api_duration", unit="s")
    _dependencies = meter.create_counter("pawlocal_dependency_requests")
    _dependency_duration = meter.create_histogram(
        "pawlocal_dependency_duration", unit="s"
    )
    _exports = meter.create_counter("pawlocal_telemetry_exports")
    _export_failures = meter.create_counter("pawlocal_telemetry_export_failures")
    traces = TracerProvider(
        resource=resource, sampler=cloud_sampler(), shutdown_on_exit=False
    )
    traces.add_span_processor(
        BatchSpanProcessor(
            SafeSpanExporter(endpoint=url + "/v1/traces", timeout=2, session=session()),
            max_queue_size=256,
            max_export_batch_size=64,
            schedule_delay_millis=1000,
            export_timeout_millis=2500,
        )
    )
    logs = LoggerProvider(resource=resource, shutdown_on_exit=False)
    logs.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=url + "/v1/logs", timeout=2, session=session()),
            max_queue_size=256,
            max_export_batch_size=64,
            schedule_delay_millis=1000,
            export_timeout_millis=2500,
        )
    )
    return traces, logs, meters, SafeCloudHandler(logger_provider=logs)
