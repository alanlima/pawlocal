from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from pawlocal.infrastructure import models  # noqa: F401
from pawlocal.infrastructure.database import Base
from pawlocal.infrastructure.models import PlaceRecord
from pawlocal.seed_places import PLACES, seed_with_engine, validate_target


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
        confirm_production=False,
    )
    with pytest.raises(ValueError, match="Aurora DSQL"):
        validate_target(
            make_url(
                "postgresql+psycopg://localhost/pawlocal?application_name=pawlocal-development"
            ),
            "development",
            confirm_production=False,
        )
    with pytest.raises(ValueError, match="application_name"):
        validate_target(
            make_url(
                "auroradsql+psycopg://app@dsql.example/postgres?application_name=pawlocal-production"
            ),
            "development",
            confirm_production=False,
        )


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


def test_seed_fails_closed_when_stable_id_has_different_content(seed_engine):
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
    with pytest.raises(RuntimeError, match="ID conflict"):
        seed_with_engine(seed_engine, "development")
    with Session(seed_engine) as session:
        assert session.query(PlaceRecord).count() == 1
