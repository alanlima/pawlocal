"""Safely seed the two source-backed Brisbane demonstration listings."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, selectinload


@dataclass(frozen=True)
class SeedPlace:
    id: UUID
    name: str
    area: str
    address: str
    description: str
    dog_access_rules: str


PLACES = (
    SeedPlace(
        id=UUID("639a0c12-6e38-4ea0-a1d0-4caabbe4bd01"),
        name="Orleigh Park",
        area="Brisbane City",
        address="68 Hill End Terrace, West End Qld 4101",
        description=(
            "Brisbane City Council identifies an off-leash dog park at Orleigh Park. "
            "Source: Brisbane City Council, Orleigh Park; checked 2026-10-19: "
            "https://www.brisbane.qld.gov.au/parks-and-recreation/parks-and-greenspaces/"
            "book-a-park-site/orleigh-park"
        ),
        dog_access_rules="Brisbane City Council identifies an off-leash dog park at this park.",
    ),
    SeedPlace(
        id=UUID("edcd490d-6c79-487a-8c3d-0af495e9d902"),
        name="Whites Hill Reserve",
        area="Brisbane City",
        address="258 Boundary Road, Camp Hill Qld 4152",
        description=(
            "Brisbane City Council identifies a dog park within Whites Hill Reserve. "
            "The Council page says dogs must be leashed in the reserve and may be off-leash "
            "only in the dog park. Source: Brisbane City Council, Whites Hill Reserve; "
            "checked 2026-10-19: "
            "https://www.brisbane.qld.gov.au/parks-and-recreation/bushland-and-wetlands/"
            "find-reserves-and-forests/whites-hill-reserve"
        ),
        dog_access_rules=(
            "Dogs must be leashed in the reserve; off-leash access is only in the dog park."
        ),
    ),
)


def validate_target(
    url: URL,
    environment: str,
    *,
    expected_endpoint: str | None,
    confirm_production: bool,
) -> None:
    """Fail before creating an engine unless its endpoint matches the env allowlist."""
    if environment not in {"development", "production"}:
        raise ValueError("environment must be development or production")
    if environment == "production" and not confirm_production:
        raise ValueError("production seeding requires --confirm-production")
    if url.get_backend_name().casefold() != "auroradsql":
        raise ValueError(
            "seeding is restricted to Aurora DSQL; PostgreSQL is not allowed"
        )
    if not expected_endpoint:
        raise ValueError(
            "PAWLOCAL_EXPECTED_DSQL_ENDPOINT must be set to the environment's approved DSQL endpoint"
        )
    if url.host is None or url.host.casefold() != expected_endpoint.strip().casefold():
        raise ValueError(
            "PAWLOCAL_DATABASE_URL host does not match PAWLOCAL_EXPECTED_DSQL_ENDPOINT"
        )
    expected = f"pawlocal-{environment}"
    application_name = url.query.get("application_name")
    if application_name != expected:
        raise ValueError(
            f"PAWLOCAL_DATABASE_URL application_name must be exactly {expected}"
        )


def _matches(record, seed: SeedPlace) -> bool:
    return (
        record.id == seed.id
        and record.name == seed.name
        and record.category == "dog_park"
        and record.area == seed.area
        and record.address == seed.address
        and record.description == seed.description
        and record.dog_access_rules == seed.dog_access_rules
        and record.facilities == []
        and record.average_rating is None
        and record.source_updated_at is None
        and record.is_published is True
    )


def _find_conflicts(session: Session, seed: SeedPlace):
    from pawlocal.infrastructure.models import PlaceRecord

    by_id = session.scalar(
        select(PlaceRecord)
        .where(PlaceRecord.id == seed.id)
        .options(selectinload(PlaceRecord.facility_records))
    )
    by_name = session.scalars(
        select(PlaceRecord)
        .where(func.lower(PlaceRecord.name) == seed.name.casefold())
        .options(selectinload(PlaceRecord.facility_records))
    ).all()
    if by_id is not None and not _matches(by_id, seed):
        raise RuntimeError(f"seed ID conflict for {seed.name} ({seed.id})")
    if any(row.id != seed.id for row in by_name):
        raise RuntimeError(f"seed name conflict for {seed.name}")
    if len(by_name) > 1:
        raise RuntimeError(f"multiple database records conflict with {seed.name}")
    return by_id


def seed_with_engine(
    engine, environment: str, *, confirm_production: bool = False
) -> list[str]:
    """Insert missing records in individual transactions and verify exact content.

    This lower-level entry point accepts an injected engine for isolated tests.
    Only ``main`` creates an engine, after validating the explicit DSQL target.
    """
    if environment not in {"development", "production"}:
        raise ValueError("environment must be development or production")
    if environment == "production" and not confirm_production:
        raise ValueError("production seeding requires --confirm-production")

    from sqlalchemy.orm import sessionmaker

    from pawlocal.infrastructure.models import PlaceRecord

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    # Preflight every stable ID and normalized name before any write.
    with SessionLocal() as session:
        for seed in PLACES:
            _find_conflicts(session, seed)

    outcomes: list[str] = []
    for seed in PLACES:
        with SessionLocal.begin() as session:
            existing = _find_conflicts(session, seed)
            if existing is None:
                session.add(
                    PlaceRecord(
                        id=seed.id,
                        name=seed.name,
                        category="dog_park",
                        area=seed.area,
                        address=seed.address,
                        description=seed.description,
                        dog_access_rules=seed.dog_access_rules,
                        facilities=[],
                        average_rating=None,
                        source_updated_at=None,
                        is_published=True,
                    )
                )
                outcomes.append(f"inserted {seed.name}")
            else:
                outcomes.append(f"already present {seed.name}")

    # Read back the exact seeded records after all per-record transactions.
    with SessionLocal() as session:
        for seed in PLACES:
            record = session.scalar(
                select(PlaceRecord)
                .where(PlaceRecord.id == seed.id)
                .options(selectinload(PlaceRecord.facility_records))
            )
            if record is None or not _matches(record, seed):
                raise RuntimeError(f"post-seed verification failed for {seed.name}")
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", required=True, choices=("development", "production")
    )
    parser.add_argument("--confirm-production", action="store_true")
    args = parser.parse_args(argv)

    try:
        from pawlocal.config import settings

        url = settings.sqlalchemy_url
        validate_target(
            url,
            args.environment,
            expected_endpoint=os.environ.get("PAWLOCAL_EXPECTED_DSQL_ENDPOINT"),
            confirm_production=args.confirm_production,
        )
        # Import only after the target guard: database.py binds its runtime engine
        # from PAWLOCAL_DATABASE_URL when imported.
        from pawlocal.infrastructure.database import engine

        try:
            for outcome in seed_with_engine(
                engine,
                args.environment,
                confirm_production=args.confirm_production,
            ):
                print(outcome)
        finally:
            engine.dispose()
    except (RuntimeError, ValueError) as exc:
        print(f"seed aborted: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
