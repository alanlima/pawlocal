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
_DSQL_ALLOWED_QUERY_KEYS = {"application_name"}
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
    """Create a supported database engine.

    PostgreSQL remains the default/local path. Aurora DSQL uses the AWS
    SQLAlchemy helper, which obtains IAM credentials through the AWS SDK
    default credential chain. No key or generated database token is read,
    stored, or placed in a database URL by this module.
    """
    backend = url.get_backend_name().lower()
    if backend == "auroradsql":
        if (url.username or "").strip().casefold() == "admin":
            raise RuntimeError(
                "Aurora DSQL reserved database role 'admin' cannot be used; "
                "configure a custom application role."
            )
        if url.password is not None or _contains_dsql_auth_query(url):
            raise RuntimeError(
                "Do not configure auth credentials in the Aurora DSQL database URL; "
                "runtime credentials must come from the approved engine factory."
            )
        unexpected_query_keys = set(url.query) - _DSQL_ALLOWED_QUERY_KEYS
        if unexpected_query_keys:
            raise RuntimeError(
                "Unsupported Aurora DSQL database URL options: "
                f"{sorted(unexpected_query_keys)}"
            )
        if not url.host or not url.database or not url.username:
            raise RuntimeError(
                "Aurora DSQL database URL must include the cluster endpoint, "
                "database name, and custom database role."
            )
        if url.port not in (None, 5432):
            raise RuntimeError("Aurora DSQL uses port 5432.")
        factory = dsql_engine_factory or _create_dsql_engine
        return factory(url)
    if backend != "postgresql":
        raise RuntimeError(f"Unsupported configured database backend: {backend}")
    return create_engine(url, pool_pre_ping=True)


def _create_dsql_engine(url: URL) -> Engine:
    """Build a DSQL engine whose connector uses the AWS SDK credential chain."""
    try:
        import certifi
        from aurora_dsql_sqlalchemy import create_dsql_engine
    except ImportError as exc:
        raise RuntimeError(
            "Aurora DSQL support is not installed; install the backend runtime "
            "dependencies before selecting this database."
        ) from exc

    engine = create_dsql_engine(
        host=url.host,
        user=url.username,
        driver="psycopg",
        dbname=url.database,
        sslrootcert=certifi.where(),
        application_name=url.query.get("application_name", "pawlocal"),
        pool_pre_ping=True,
    )
    event.listen(engine, "begin", _set_dsql_search_path)
    return engine


def _set_dsql_search_path(connection) -> None:
    """Keep unqualified DSQL model and migration SQL inside the app schema."""
    connection.exec_driver_sql("SET LOCAL search_path TO pawlocal")


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
