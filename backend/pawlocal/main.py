import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pawlocal.api.routes import router
from pawlocal.config import settings
from pawlocal.observability import (
    configure_observability,
    create_api_span,
    extract_trace_context,
    log_request,
    mark_failed,
    safe_exception_log_fields,
    shutdown_observability,
    synthetic_database_failure,
)

configure_observability()


def add_cors_middleware(app: FastAPI, origins: list[str]) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "traceparent",
            "tracestate",
        ],
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    shutdown_observability()


app = FastAPI(
    title="PawLocal API",
    version="0.1.0",
    lifespan=lifespan,
    telemetry={
        "tracing": False,
        "metrics": False,
        "logs": False,
        "operation_spans": False,
        "auto_configure": False,
    },
)
app.include_router(router, prefix=settings.api_prefix)
add_cors_middleware(app, settings.cors_origins)


@app.middleware("http")
async def trace_and_log_request(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    started = perf_counter()
    context = extract_trace_context(request.headers)
    with create_api_span(f"HTTP {request.method}", context) as span:
        span.set_attribute("http.request.method", request.method)
        log_request(
            logging.DEBUG,
            "API request started",
            span=span,
            event_code="api.request.started",
            operation="http_request",
        )
        failure = request.headers.get("x-pawlocal-demo-failure")
        if settings.demo_faults_enabled and failure in {"api", "database"}:
            code = (
                "synthetic_api_unavailable"
                if failure == "api"
                else "synthetic_database_unavailable"
            )
            if failure == "database":
                synthetic_database_failure(span)
            mark_failed(span, code)
            log_request(
                logging.ERROR,
                "Synthetic dependency failure",
                span=span,
                event_code="api.synthetic_failure",
                operation="http_request",
                outcome="error",
                http_status=503,
                error_code=code,
            )
            span.set_attribute("http.response.status_code", 503)
            return JSONResponse(
                status_code=503,
                content={"code": code, "message": "Service temporarily unavailable"},
            )

        error_code = None
        exception_fields = {}
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - keep response and logs message-free
            error_code = "unhandled_api_error"
            exception_fields = safe_exception_log_fields(exc)
            mark_failed(span, error_code)
            response = JSONResponse(
                status_code=500,
                content={
                    "code": "internal_error",
                    "message": "Request could not be completed",
                },
            )

        route = request.scope.get("route")
        operation = getattr(route, "path", "unmatched")
        status_code = response.status_code
        outcome = "success" if status_code < 400 else "error"
        span.set_attribute("http.route", operation)
        span.set_attribute("http.response.status_code", status_code)
        if status_code >= 500:
            error_code = error_code or "api_request_failed"
            mark_failed(span, error_code)
        duration_ms = round((perf_counter() - started) * 1000, 2)
        level = (
            logging.ERROR
            if status_code >= 500
            else logging.WARNING
            if status_code >= 400
            else logging.INFO
        )
        log_request(
            level,
            "API request completed",
            span=span,
            event_code="api.request.completed",
            operation=operation,
            outcome=outcome,
            http_status=status_code,
            duration_ms=duration_ms,
            error_code=error_code if status_code >= 500 else None,
            **(exception_fields if error_code == "unhandled_api_error" else {}),
        )
        from pawlocal.cloud_telemetry import record_request

        record_request(operation, request.method, status_code, duration_ms / 1000)
        return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "bad_request", "message": "Invalid request parameters"},
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        content = detail
    else:
        content = {"code": "http_error", "message": "Request could not be completed"}
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=exc.headers
    )


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "environment": settings.release_environment or "local",
        "image_digest": settings.release_image_digest or "unknown",
        "telemetry_enabled": settings.telemetry_enabled,
    }
