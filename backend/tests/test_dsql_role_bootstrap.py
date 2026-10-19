from __future__ import annotations

import pytest
from pawlocal.dsql_role_bootstrap import ensure_app_role


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeConnection:
    def __init__(self, results, statements):
        self.results = iter(results)
        self.statements = statements

    def execute(self, _statement, _parameters):
        return next(self.results)

    def exec_driver_sql(self, statement):
        self.statements.append(statement)


class FakeBegin:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


class FakeEngine:
    def __init__(self, results):
        self.results = iter(results)
        self.transactions: list[list[str]] = []

    def begin(self):
        statements: list[str] = []
        self.transactions.append(statements)
        return FakeBegin(FakeConnection(self.results, statements))

    @property
    def statements(self):
        return [statement for transaction in self.transactions for statement in transaction]


@pytest.fixture
def app_identity():
    return (
        "pawlocal_development_app",
        "arn:aws:iam::123456789012:user/pawlocal/pawlocal-development-dsql-app",
    )


def test_bootstrap_creates_role_maps_user_and_grants_schema(app_identity):
    engine = FakeEngine(
        [FakeResult(None), FakeResult(None), FakeResult(None)]
    )

    ensure_app_role(engine, *app_identity)

    assert engine.statements == [
        'CREATE ROLE "pawlocal_development_app" WITH LOGIN',
        "AWS IAM GRANT pawlocal_development_app TO 'arn:aws:iam::123456789012:user/pawlocal/pawlocal-development-dsql-app'",
        'CREATE SCHEMA "pawlocal"',
        'GRANT USAGE, CREATE ON SCHEMA "pawlocal" TO "pawlocal_development_app"',
    ]
    assert all(len(transaction) <= 1 for transaction in engine.transactions)


def test_bootstrap_is_idempotent_for_existing_role_and_mapping(app_identity):
    engine = FakeEngine(
        [FakeResult(1), FakeResult(app_identity[0]), FakeResult(1)]
    )

    ensure_app_role(engine, *app_identity)

    assert engine.statements == [
        'GRANT USAGE, CREATE ON SCHEMA "pawlocal" TO "pawlocal_development_app"'
    ]


def test_bootstrap_rejects_user_mapped_to_another_role(app_identity):
    engine = FakeEngine([FakeResult(1), FakeResult("unexpected_role")])

    with pytest.raises(RuntimeError, match="different DSQL database role"):
        ensure_app_role(engine, *app_identity)

    assert engine.statements == []


@pytest.mark.parametrize(
    ("database_role", "iam_user_arn"),
    [
        ("bad role", "arn:aws:iam::123456789012:user/app"),
        ("pawlocal_app", "not-an-arn"),
    ],
)
def test_bootstrap_validates_identifiers_before_connecting(database_role, iam_user_arn):
    engine = FakeEngine([])

    with pytest.raises(ValueError):
        ensure_app_role(engine, database_role, iam_user_arn)

    assert engine.statements == []
