from collections.abc import Callable, Generator
from contextlib import AbstractContextManager

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from pawlocal.config import settings


class Base(DeclarativeBase):
    pass


DSQLEngineFactory = Callable[[URL], Engine]
_DSQL_AUTH_QUERY_MARKERS = (
    "auth",
    "token",
    "password",
    "passwd",
    "pwd",
    "secret",
    "credential",
    "accesskey",
    "apikey",
    "jwt",
    "privatekey",
    "signingkey",
    "signature",
    "bearer",
)


def _contains_dsql_auth_query(url: URL) -> bool:
    for key in url.query:
        normalized = "".join(char for char in key.casefold() if char.isalnum())
        if any(marker in normalized for marker in _DSQL_AUTH_QUERY_MARKERS):
            return True
    return False


def create_database_engine(
    url: URL, *, dsql_engine_factory: DSQLEngineFactory | None = None
) -> Engine:
    """Create a supported database engine without guessing DSQL credentials.

    PostgreSQL remains the default/local path. Aurora DSQL requires an explicit
    factory so the deployment runtime can supply an approved short-lived AWS
    credential source; this module does not select one or accept token values.
    """
    backend = url.get_backend_name().lower()
    if backend == "auroradsql":
        if url.password is not None or _contains_dsql_auth_query(url):
            raise RuntimeError(
                "Do not configure auth credentials in the Aurora DSQL database URL; "
                "runtime credentials must come from the approved engine factory."
            )
        if dsql_engine_factory is None:
            raise RuntimeError(
                "Aurora DSQL is not runtime-configured; provide an approved "
                "DSQL engine factory before selecting this database."
            )
        return dsql_engine_factory(url)
    if backend != "postgresql":
        raise RuntimeError(f"Unsupported configured database backend: {backend}")
    return create_engine(url, pool_pre_ping=True)


engine = create_database_engine(settings.sqlalchemy_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _start_query_span(conn, _cursor, statement, _parameters, _context, _many):
    # SQL and bind values are deliberately not recorded: they may contain user data.
    manager: AbstractContextManager = trace.get_tracer(
        "pawlocal.database"
    ).start_as_current_span(
        "db.query",
        kind=SpanKind.CLIENT,
        attributes={"db.system": conn.dialect.name, "db.operation.name": "query"},
        record_exception=False,
        set_status_on_exception=False,
    )
    span = manager.__enter__()
    conn.info.setdefault("pawlocal_query_spans", []).append((manager, span))


def _finish_query_span(conn, error: BaseException | None = None) -> None:
    managers = conn.info.get("pawlocal_query_spans", [])
    if not managers:
        return
    manager, span = managers.pop()
    if error is not None:
        span.set_status(Status(StatusCode.ERROR, "database_operation_failed"))
        span.set_attribute("error.code", "database_operation_failed")
    # Do not pass exception details to OTel; DB exceptions can contain SQL or bind values.
    manager.__exit__(None, None, None)


event.listen(Engine, "before_cursor_execute", _start_query_span)


def _query_succeeded(conn, _cursor, _statement, _parameters, _context, _many) -> None:
    _finish_query_span(conn)


event.listen(Engine, "after_cursor_execute", _query_succeeded)


@event.listens_for(Engine, "handle_error")
def _query_failed(exception_context) -> None:
    if exception_context.connection is not None:
        _finish_query_span(
            exception_context.connection, exception_context.original_exception
        )


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
