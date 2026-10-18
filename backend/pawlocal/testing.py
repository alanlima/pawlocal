"""Safety checks shared by explicit local test harnesses."""

from sqlalchemy.engine import make_url


def validate_e2e_database_url(database_url: str | None, allow_reset: str | None) -> str:
    """Require explicit opt-in and a visibly disposable PostgreSQL database name."""
    if allow_reset != "true":
        raise RuntimeError(
            "Set PAWLOCAL_E2E_ALLOW_RESET=true to allow migrations and synthetic-data reset."
        )
    if not database_url:
        raise RuntimeError(
            "Set PAWLOCAL_E2E_DATABASE_URL to a dedicated disposable PostgreSQL database."
        )

    try:
        url = make_url(database_url)
    except Exception as error:
        raise RuntimeError(
            "PAWLOCAL_E2E_DATABASE_URL is not a valid SQLAlchemy URL."
        ) from error

    if url.get_backend_name() != "postgresql":
        raise RuntimeError("The browser E2E database must use PostgreSQL.")
    database_name = (url.database or "").lower().replace("-", "_")
    name_parts = set(database_name.split("_"))
    if not name_parts.intersection({"test", "e2e", "verify"}):
        raise RuntimeError(
            "The E2E database name must contain a `_test`, `_e2e`, or `_verify` segment."
        )
    return database_url
