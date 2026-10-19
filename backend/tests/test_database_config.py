import pytest
from sqlalchemy.engine import make_url

from pawlocal.config import Settings


def test_compose_database_fields_preserve_url_special_password_characters():
    password = "value@with:/?#%[]reserved"
    settings = Settings(
        _env_file=None,
        database_host="postgres",
        database_port=5432,
        database_name="pawlocal",
        database_user="pawlocal",
        database_password=password,
    )

    url = settings.sqlalchemy_url
    assert url.password == password
    assert url.host == "postgres"
    assert url.port == 5432
    assert url.database == "pawlocal"
    assert make_url(url.render_as_string(hide_password=False)).password == password


def test_database_engine_keeps_postgresql_as_the_default_path():
    from pawlocal.infrastructure.database import create_database_engine

    engine = create_database_engine(Settings(_env_file=None).sqlalchemy_url)
    try:
        assert engine.dialect.name == "postgresql"
    finally:
        engine.dispose()


def test_dsql_engine_requires_an_explicit_runtime_factory():
    from pawlocal.infrastructure.database import create_database_engine

    with pytest.raises(RuntimeError, match="not runtime-configured"):
        create_database_engine(make_url("auroradsql+psycopg://cluster/db"))


@pytest.mark.parametrize(
    "query_key",
    [
        "token",
        "Auth_Token",
        "ACCESS-TOKEN",
        "authorization",
        "Password",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "client_secret",
        "api_key",
        "sslpassword",
        "jwt",
        "id_token",
        "refresh_token",
        "x-amz-security-token",
        "db_password",
        "secret",
        "pwd",
        "custom_auth_hint",
        "my_private_key",
        "custom_jwt_value",
        "signing_signature",
    ],
)
def test_dsql_database_url_rejects_auth_query_parameters(query_key):
    from pawlocal.infrastructure.database import create_database_engine

    url = make_url(f"auroradsql+psycopg://admin@cluster/db?{query_key}=secret")
    with pytest.raises(RuntimeError, match="Do not configure auth credentials"):
        create_database_engine(url, dsql_engine_factory=lambda _: object())


def test_dsql_engine_factory_receives_the_url_without_static_password():
    from pawlocal.infrastructure.database import create_database_engine

    url = make_url("auroradsql+psycopg://cluster/db?application_name=pawlocal")
    engine = object()
    received = []

    def factory(database_url):
        received.append(database_url)
        return engine

    assert create_database_engine(url, dsql_engine_factory=factory) is engine
    assert received == [url]


def test_unknown_database_backend_fails_closed():
    from pawlocal.infrastructure.database import create_database_engine

    with pytest.raises(RuntimeError, match="Unsupported configured database backend"):
        create_database_engine(make_url("mysql+pymysql://db/name"))
