from __future__ import annotations

import pytest

from pawlocal.dsql_role_bootstrap import ensure_app_role, verify_app_role


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeResult:
    def __init__(self, value=None, *, scalars=None, row=None):
        self.value = value
        self.scalar_values = scalars
        self.row = row

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return FakeScalars(self.scalar_values)

    def one(self):
        return self.row


class FakeConnection:
    def __init__(self, results, statements, queries):
        self.results = results
        self.statements = statements
        self.queries = queries

    def execute(self, statement, _parameters):
        self.queries.append(str(statement))
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
        self.queries: list[str] = []

    def begin(self):
        statements: list[str] = []
        self.transactions.append(statements)
        return FakeBegin(FakeConnection(self.results, statements, self.queries))

    @property
    def statements(self):
        return [statement for tx in self.transactions for statement in tx]


@pytest.fixture
def app_identity():
    return (
        "pawlocal_development_app",
        "arn:aws:iam::123456789012:role/pawlocal-development-dsql-runtime",
    )


def _verified_results(database_role, principal):
    return [
        FakeResult(True),
        FakeResult(scalars=[principal]),
        FakeResult(scalars=[database_role]),
        FakeResult(row=(True, True)),
        FakeResult(row=(False, False)),
    ]


def test_bootstrap_creates_exact_role_mapping_and_schema_grants(app_identity):
    role, principal = app_identity
    engine = FakeEngine(
        [
            FakeResult(None),
            FakeResult(scalars=[]),
            FakeResult(scalars=[]),
            FakeResult(None),
            *_verified_results(role, principal),
        ]
    )

    ensure_app_role(engine, role, principal)

    assert engine.statements == [
        f'CREATE ROLE "{role}" WITH LOGIN',
        f"AWS IAM GRANT {role} TO '{principal}'",
        'CREATE SCHEMA "pawlocal"',
        f'GRANT USAGE, CREATE ON SCHEMA "pawlocal" TO "{role}"',
    ]
    assert all(len(transaction) <= 1 for transaction in engine.transactions)


def test_bootstrap_is_idempotent_and_rechecks_postconditions(app_identity):
    role, principal = app_identity
    engine = FakeEngine(
        [
            FakeResult(True),
            FakeResult(scalars=[principal]),
            FakeResult(scalars=[role]),
            FakeResult(1),
            *_verified_results(role, principal),
        ]
    )

    ensure_app_role(engine, role, principal)

    assert engine.statements == [
        f'GRANT USAGE, CREATE ON SCHEMA "pawlocal" TO "{role}"'
    ]


@pytest.mark.parametrize(
    ("role_principals", "principal_roles"),
    [
        (["unexpected_principal"], []),
        ([], ["unexpected_role"]),
        (
            [
                "arn:aws:iam::123456789012:role/pawlocal-development-dsql-runtime",
                "unexpected_principal",
            ],
            ["pawlocal_development_app"],
        ),
    ],
)
def test_bootstrap_rejects_competing_principal_mapping(
    app_identity, role_principals, principal_roles
):
    engine = FakeEngine(
        [
            FakeResult(True),
            FakeResult(scalars=role_principals),
            FakeResult(scalars=principal_roles),
        ]
    )

    with pytest.raises(RuntimeError, match="competing mapping"):
        ensure_app_role(engine, *app_identity)

    assert engine.statements == []


@pytest.mark.parametrize(
    ("role_principals", "principal_roles", "grants", "public_grants"),
    [
        (["expected", "competing"], ["role"], (True, True), (False, False)),
        (["expected"], ["role", "other"], (True, True), (False, False)),
        (["expected"], ["role"], (True, False), (False, False)),
    ],
)
def test_postconditions_fail_closed_on_mapping_or_grant_drift(
    role_principals, principal_roles, grants, public_grants
):
    role = "role"
    principal = "expected"
    engine = FakeEngine(
        [
            FakeResult(True),
            FakeResult(scalars=role_principals),
            FakeResult(scalars=principal_roles),
            FakeResult(row=grants),
            FakeResult(row=public_grants),
        ]
    )

    with pytest.raises(RuntimeError):
        verify_app_role(engine, role, principal)


@pytest.mark.parametrize(
    "public_grants",
    [(True, False), (False, True)],
    ids=["public-usage", "public-create"],
)
def test_public_schema_usage_or_create_grant_fails_closed(public_grants):
    role = "role"
    principal = "expected"
    engine = FakeEngine(
        [
            FakeResult(True),
            FakeResult(scalars=[principal]),
            FakeResult(scalars=[role]),
            FakeResult(row=(True, True)),
            FakeResult(row=public_grants),
        ]
    )

    with pytest.raises(RuntimeError, match="PUBLIC"):
        verify_app_role(engine, role, principal)


def test_public_grants_are_read_from_schema_acl_not_role_privilege_function(
    app_identity,
):
    role, principal = app_identity
    engine = FakeEngine(_verified_results(role, principal))

    verify_app_role(engine, role, principal)

    sql = "\n".join(engine.queries).lower()
    assert "has_schema_privilege('public'" not in sql
    assert "pg_catalog.aclexplode" in sql
    assert "privilege_data.grantee = 0" in sql
    assert "privilege_data.privilege_type = 'usage'" in sql
    assert "privilege_data.privilege_type = 'create'" in sql


@pytest.mark.parametrize(
    ("database_role", "iam_principal_arn"),
    [
        ("bad role", "arn:aws:iam::123456789012:role/pawlocal-runtime"),
        ("pawlocal_app", "not-an-arn"),
    ],
)
def test_bootstrap_validates_identifiers_before_connecting(
    database_role, iam_principal_arn
):
    engine = FakeEngine([])

    with pytest.raises(ValueError):
        ensure_app_role(engine, database_role, iam_principal_arn)

    assert engine.statements == []
