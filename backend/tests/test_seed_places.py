from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from pawlocal.infrastructure import models  # noqa: F401
from pawlocal.infrastructure.database import Base
from pawlocal.infrastructure.models import PlaceRecord
from pawlocal.seed_places import (
    load_catalog,
    seed_with_engine,
    validate_target,
    verify_dsql_app_schema,
)

PLACES = load_catalog()


@pytest.fixture
def seed_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_target_guard_requires_matching_dsql_environment():
    validate_target(
        make_url(
            "auroradsql+psycopg://app@dsql.example/postgres?application_name=pawlocal-development"
        ),
        "development",
        expected_endpoint="dsql.example",
        confirm_production=False,
    )
    with pytest.raises(ValueError, match="Aurora DSQL"):
        validate_target(
            make_url(
                "postgresql+psycopg://localhost/pawlocal?application_name=pawlocal-development"
            ),
            "development",
            expected_endpoint="dsql.example",
            confirm_production=False,
        )
    with pytest.raises(ValueError, match="application_name"):
        validate_target(
            make_url(
                "auroradsql+psycopg://app@dsql.example/postgres?application_name=pawlocal-production"
            ),
            "development",
            expected_endpoint="dsql.example",
            confirm_production=False,
        )


def test_target_guard_rejects_production_endpoint_with_development_name():
    with pytest.raises(ValueError, match="does not match"):
        validate_target(
            make_url(
                "auroradsql+psycopg://app@dsql-production.dsql.ap-southeast-2.on.aws/postgres?application_name=pawlocal-development"
            ),
            "development",
            expected_endpoint="dsql-development.dsql.ap-southeast-2.on.aws",
            confirm_production=False,
        )


def test_target_guard_requires_environment_endpoint_allowlist():
    with pytest.raises(ValueError, match="PAWLOCAL_EXPECTED_DSQL_ENDPOINT"):
        validate_target(
            make_url(
                "auroradsql+psycopg://app@dsql-development.dsql.ap-southeast-2.on.aws/postgres?application_name=pawlocal-development"
            ),
            "development",
            expected_endpoint=None,
            confirm_production=False,
        )


@pytest.mark.parametrize("schema", ["pawlocal", "public"])
def test_dsql_seed_schema_guard_requires_api_schema(schema):
    from contextlib import contextmanager
    from types import SimpleNamespace

    class Connection:
        def scalar(self, _statement):
            return schema

    class Engine:
        dialect = SimpleNamespace(name="auroradsql")

        @contextmanager
        def connect(self):
            yield Connection()

    if schema == "pawlocal":
        verify_dsql_app_schema(Engine())
    else:
        with pytest.raises(RuntimeError, match="runtime schema does not match"):
            verify_dsql_app_schema(Engine())


def test_production_requires_explicit_confirmation(seed_engine):
    with pytest.raises(ValueError, match="--confirm-production"):
        seed_with_engine(seed_engine, "production")


def test_seed_is_exact_and_idempotent(seed_engine):
    first = seed_with_engine(seed_engine, "development")
    second = seed_with_engine(seed_engine, "development")
    assert first == ["inserted Orleigh Park", "inserted Whites Hill Reserve"]
    assert second == [
        "already present Orleigh Park",
        "already present Whites Hill Reserve",
    ]


def test_catalog_file_is_the_seed_source_of_truth():
    assert load_catalog() == PLACES
    assert len(PLACES) == 2


def test_seed_updates_catalog_fields_by_stable_id_and_preserves_user_data(seed_engine):
    from sqlalchemy.orm import Session

    seed_with_engine(seed_engine, "development")
    original = PLACES[0]
    with Session(seed_engine) as session, session.begin():
        record = session.get(PlaceRecord, original.id)
        record.average_rating = 4.5
        record.source_updated_at = datetime(2026, 10, 20, tzinfo=UTC)

    updated_seed = replace(
        original,
        name="Orleigh Park Updated",
        area="West End",
        facilities=("Off-leash area", "Drinking water"),
    )
    outcomes = seed_with_engine(seed_engine, "development", places=(updated_seed,))
    assert outcomes == ["updated Orleigh Park Updated"]
    with Session(seed_engine) as session:
        record = session.get(PlaceRecord, original.id)
        assert record.name == "Orleigh Park Updated"
        assert record.area == "West End"
        assert record.facilities == ["Off-leash area", "Drinking water"]
        assert record.average_rating == 4.5
        assert record.source_updated_at.replace(tzinfo=UTC) == datetime(
            2026, 10, 20, tzinfo=UTC
        )


def test_seed_does_not_delete_records_removed_from_catalog(seed_engine):
    from sqlalchemy.orm import Session

    orphaned_id = uuid4()
    with Session(seed_engine) as session, session.begin():
        session.add(
            PlaceRecord(
                id=orphaned_id,
                name="Previously seeded place",
                category="dog_park",
                area="Brisbane City",
                is_published=True,
            )
        )

    seed_with_engine(seed_engine, "development", places=(PLACES[0],))

    with Session(seed_engine) as session:
        assert session.get(PlaceRecord, orphaned_id) is not None


def test_seed_fails_closed_on_name_conflict_before_any_insert(seed_engine):
    from sqlalchemy.orm import Session

    with Session(seed_engine) as session, session.begin():
        session.add(
            PlaceRecord(
                id=uuid4(),
                name=PLACES[1].name,
                category="dog_park",
                area="Other",
                is_published=True,
            )
        )
    with pytest.raises(RuntimeError, match="name conflict"):
        seed_with_engine(seed_engine, "development")
    with Session(seed_engine) as session:
        assert session.get(PlaceRecord, PLACES[0].id) is None


def test_seed_updates_existing_stable_id_content(seed_engine):
    from sqlalchemy.orm import Session

    seed = PLACES[0]
    with Session(seed_engine) as session, session.begin():
        session.add(
            PlaceRecord(
                id=seed.id,
                name="Different listing",
                category="dog_park",
                area="West End",
                is_published=True,
            )
        )
    outcome = seed_with_engine(seed_engine, "development", places=(seed,))
    assert outcome == ["updated Orleigh Park"]
    with Session(seed_engine) as session:
        record = session.get(PlaceRecord, seed.id)
        assert record.name == seed.name
        assert record.address == seed.address
