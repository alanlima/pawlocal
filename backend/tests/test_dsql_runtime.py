from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from pawlocal.infrastructure.community import CommunityRepository
from pawlocal.infrastructure.models import PlaceRecord
from pawlocal.infrastructure.places import build_search_statement


def test_place_search_compiles_to_normalized_dsql_exists_query():
    dsql_psycopg = pytest.importorskip("aurora_dsql_sqlalchemy.psycopg")
    statement = build_search_statement(
        query="park%_",
        area="Brisbane City",
        category="dog_park",
        facilities=["Fenced", "Shade", "Fenced"],
    )
    dialect = dsql_psycopg.AuroraDSQLDialect_psycopg()
    query_sql = str(
        statement.order_by(PlaceRecord.name, PlaceRecord.id)
        .offset(20)
        .limit(10)
        .compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    ).upper()
    count_sql = str(
        select(func.count()).select_from(statement.subquery()).compile(
            dialect=dialect, compile_kwargs={"literal_binds": True}
        )
    ).upper()

    assert "EXISTS" in query_sql
    assert query_sql.count("EXISTS") == 2
    assert "ILIKE" in query_sql
    assert "LIMIT 10" in query_sql
    assert "OFFSET 20" in query_sql
    assert "ANY(" not in query_sql
    assert "PLACES.FACILITIES" not in query_sql
    assert "COUNT(*)" in count_sql


class _FakeSession:
    def __init__(self):
        self.rollbacks = 0
        self.dialect = SimpleNamespace(name="auroradsql")

    def get_bind(self):
        return SimpleNamespace(dialect=self.dialect)

    def rollback(self):
        self.rollbacks += 1


def _serialization_error(code):
    original = SimpleNamespace(sqlstate=code)
    return DBAPIError("statement", None, original, hide_parameters=True)


def test_review_transaction_retries_dsql_occ_and_returns_on_success(monkeypatch):
    session = _FakeSession()
    repository = CommunityRepository(session)
    outcomes = iter([_serialization_error("40001"), "submitted"])
    calls = []

    def submit_once(subject, values):
        calls.append((subject, values))
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(repository, "_submit_contribution_once", submit_once)
    monkeypatch.setattr("pawlocal.infrastructure.community.sleep", lambda _: None)

    assert repository.submit_contribution("subject", {"kind": "review"}) == "submitted"
    assert len(calls) == 2
    assert session.rollbacks == 1


@pytest.mark.parametrize("code", ["40001", "OC000", "OC001"])
def test_review_transaction_stops_after_bounded_dsql_conflict_retries(monkeypatch, code):
    session = _FakeSession()
    repository = CommunityRepository(session)
    calls = 0

    def submit_once(_subject, _values):
        nonlocal calls
        calls += 1
        raise _serialization_error(code)

    monkeypatch.setattr(repository, "_submit_contribution_once", submit_once)
    monkeypatch.setattr("pawlocal.infrastructure.community.sleep", lambda _: None)

    with pytest.raises(DBAPIError):
        repository.submit_contribution("subject", {"kind": "review"})
    assert calls == 3
    assert session.rollbacks == 3


def test_review_transaction_does_not_retry_non_dsql_errors(monkeypatch):
    session = _FakeSession()
    session.dialect.name = "postgresql"
    repository = CommunityRepository(session)
    calls = 0

    def submit_once(_subject, _values):
        nonlocal calls
        calls += 1
        raise _serialization_error("40001")

    monkeypatch.setattr(repository, "_submit_contribution_once", submit_once)

    with pytest.raises(DBAPIError):
        repository.submit_contribution("subject", {"kind": "review"})
    assert calls == 1
    assert session.rollbacks == 1
