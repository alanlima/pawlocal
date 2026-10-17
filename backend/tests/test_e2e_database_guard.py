import pytest

from pawlocal.testing import validate_e2e_database_url


def test_e2e_database_guard_requires_explicit_reset_consent() -> None:
    with pytest.raises(RuntimeError, match="PAWLOCAL_E2E_ALLOW_RESET=true"):
        validate_e2e_database_url(
            "postgresql+psycopg://user:password@localhost/pawlocal_stage3_verify",
            None,
        )


def test_e2e_database_guard_requires_an_explicit_url() -> None:
    with pytest.raises(RuntimeError, match="PAWLOCAL_E2E_DATABASE_URL"):
        validate_e2e_database_url(None, "true")


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user:password@localhost/pawlocal",
        "sqlite:///pawlocal_stage3_verify.db",
    ],
)
def test_e2e_database_guard_rejects_non_disposable_or_non_postgres_urls(
    database_url: str,
) -> None:
    with pytest.raises(RuntimeError):
        validate_e2e_database_url(database_url, "true")


def test_e2e_database_guard_accepts_named_disposable_database() -> None:
    database_url = "postgresql+psycopg://user:password@localhost/pawlocal_stage3_verify"

    assert validate_e2e_database_url(database_url, "true") == database_url
