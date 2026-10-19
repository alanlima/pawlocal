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


def test_dsql_engine_uses_the_runtime_factory_by_default(monkeypatch):
    from pawlocal.infrastructure.database import create_database_engine

    engine = object()
    calls = []

    def factory(url):
        calls.append(url)
        return engine

    monkeypatch.setattr("pawlocal.infrastructure.database._create_dsql_engine", factory)
    url = make_url("auroradsql+psycopg://pawlocal_app@cluster/db")
    assert create_database_engine(url) is engine
    assert calls == [url]


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

    url = make_url(f"auroradsql+psycopg://pawlocal_app@cluster/db?{query_key}=secret")
    with pytest.raises(RuntimeError, match="Do not configure auth credentials"):
        create_database_engine(url, dsql_engine_factory=lambda _: object())


def test_dsql_engine_factory_receives_the_url_without_static_password():
    from pawlocal.infrastructure.database import create_database_engine

    url = make_url(
        "auroradsql+psycopg://pawlocal_app@cluster/db?application_name=pawlocal"
    )
    engine = object()
    received = []

    def factory(database_url):
        received.append(database_url)
        return engine

    assert create_database_engine(url, dsql_engine_factory=factory) is engine
    assert received == [url]


@pytest.mark.parametrize("username", ["admin", "Admin", " ADMIN "])
def test_dsql_engine_rejects_reserved_admin_role(username):
    from pawlocal.infrastructure.database import create_database_engine

    encoded_username = username.replace(" ", "%20")
    url = make_url(f"auroradsql+psycopg://{encoded_username}@cluster/db")
    with pytest.raises(RuntimeError, match="reserved database role 'admin'"):
        create_database_engine(url, dsql_engine_factory=lambda _: object())


def test_dsql_settings_reject_reserved_admin_role():
    settings = Settings(
        _env_file=None,
        database_url="auroradsql+psycopg://admin@cluster/db",
    )

    with pytest.raises(ValueError, match="reserved database role 'admin'"):
        _ = settings.sqlalchemy_url


def test_dsql_engine_delegates_to_aws_connector_using_role_and_default_chain(
    monkeypatch,
):
    import sys
    from types import ModuleType

    import certifi
    from sqlalchemy import create_engine, event

    from pawlocal.infrastructure.database import _create_dsql_engine

    calls = []
    engine = create_engine("sqlite://")

    def create_dsql_engine(**kwargs):
        calls.append(kwargs)
        return engine

    package = ModuleType("aurora_dsql_sqlalchemy")
    package.create_dsql_engine = create_dsql_engine
    monkeypatch.setitem(sys.modules, "aurora_dsql_sqlalchemy", package)

    url = make_url(
        "auroradsql+psycopg://pawlocal_dev@cluster.dsql.ap-southeast-2.on.aws/"
        "postgres?application_name=pawlocal-dev"
    )
    assert _create_dsql_engine(url) is engine
    from pawlocal.infrastructure.database import _set_dsql_search_path

    assert event.contains(engine, "begin", _set_dsql_search_path)
    assert calls == [
        {
            "host": "cluster.dsql.ap-southeast-2.on.aws",
            "user": "pawlocal_dev",
            "driver": "psycopg",
            "dbname": "postgres",
            "sslmode": "verify-full",
            "sslrootcert": certifi.where(),
            "application_name": "pawlocal-dev",
            "connect_args": {},
            "pool_pre_ping": True,
        }
    ]
    engine.dispose()


def test_dsql_engine_passes_refreshable_role_provider_to_connector(monkeypatch):
    import sys
    from types import ModuleType

    from sqlalchemy import create_engine

    from pawlocal.config import Settings
    from pawlocal.infrastructure.database import _create_dsql_engine

    calls = []
    engine = create_engine("sqlite://")
    package = ModuleType("aurora_dsql_sqlalchemy")
    package.create_dsql_engine = lambda **kwargs: calls.append(kwargs) or engine
    monkeypatch.setitem(sys.modules, "aurora_dsql_sqlalchemy", package)
    monkeypatch.setattr(
        "pawlocal.infrastructure.database.settings",
        Settings(
            _env_file=None,
            dsql_assume_role_arn="arn:aws:iam::123456789012:role/pawlocal-dsql",
        ),
    )

    _create_dsql_engine(
        make_url(
            "auroradsql+psycopg://pawlocal_app@cluster.dsql.ap-southeast-2.on.aws/postgres"
        )
    )

    provider = calls[0]["connect_args"]["custom_credentials_provider"]
    assert provider._role_arn == "arn:aws:iam::123456789012:role/pawlocal-dsql"
    engine.dispose()


def test_dsql_engine_installs_schema_search_path_for_each_transaction(monkeypatch):
    import sys
    from types import ModuleType

    from sqlalchemy import create_engine, event

    from pawlocal.infrastructure.database import (
        _create_dsql_engine,
        _set_dsql_search_path,
    )

    engine = create_engine("sqlite://")
    package = ModuleType("aurora_dsql_sqlalchemy")
    package.create_dsql_engine = lambda **_kwargs: engine
    monkeypatch.setitem(sys.modules, "aurora_dsql_sqlalchemy", package)

    configured = _create_dsql_engine(
        make_url(
            "auroradsql+psycopg://pawlocal_app@cluster.dsql.ap-southeast-2.on.aws/postgres"
        )
    )

    assert configured is engine
    assert event.contains(engine, "begin", _set_dsql_search_path)
    connection_statements = []

    class FakeConnection:
        def exec_driver_sql(self, statement):
            connection_statements.append(statement)

    _set_dsql_search_path(FakeConnection())
    assert connection_statements == ["SET LOCAL search_path TO pawlocal"]
    engine.dispose()


def test_dsql_runtime_factory_builds_aws_dialect_without_connecting():
    from pawlocal.infrastructure.database import _create_dsql_engine

    engine = _create_dsql_engine(
        make_url(
            "auroradsql+psycopg://pawlocal_app@cluster.dsql.ap-southeast-2.on.aws/"
            "postgres"
        )
    )
    try:
        assert engine.dialect.name == "auroradsql"
        assert engine.url.password is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("query_key", ["sslmode", "connect_timeout", "region"])
def test_dsql_database_url_rejects_unconsumed_options(query_key):
    from pawlocal.infrastructure.database import create_database_engine

    url = make_url(f"auroradsql+psycopg://pawlocal_app@cluster/db?{query_key}=value")
    with pytest.raises(
        RuntimeError, match="Unsupported Aurora DSQL database URL options"
    ):
        create_database_engine(url, dsql_engine_factory=lambda _: object())


@pytest.mark.parametrize(
    "database_url",
    [
        "auroradsql+psycopg://cluster/db",
        "auroradsql+psycopg://pawlocal_app@/db",
        "auroradsql+psycopg://pawlocal_app@cluster/",
    ],
)
def test_dsql_database_url_requires_endpoint_database_and_role(database_url):
    from pawlocal.infrastructure.database import create_database_engine

    with pytest.raises(RuntimeError, match="must include the cluster endpoint"):
        create_database_engine(
            make_url(database_url), dsql_engine_factory=lambda _: object()
        )


def test_unknown_database_backend_fails_closed():
    from pawlocal.infrastructure.database import create_database_engine

    with pytest.raises(RuntimeError, match="Unsupported configured database backend"):
        create_database_engine(make_url("mysql+pymysql://db/name"))
