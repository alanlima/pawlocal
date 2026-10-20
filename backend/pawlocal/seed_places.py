"""Safely seed the two source-backed Brisbane demonstration listings."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, selectinload


@dataclass(frozen=True)
class SeedPlace:
    id: UUID
    name: str
    category: str
    area: str
    address: str
    description: str
    dog_access_rules: str
    facilities: tuple[str, ...]
    is_published: bool


DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "data/seed_places.json"
_SEED_FIELDS = {
    "id",
    "name",
    "category",
    "area",
    "address",
    "description",
    "dog_access_rules",
    "facilities",
    "is_published",
}
_PLACE_CATEGORIES = {"dog_park", "beach", "walk", "hiking_area", "cafe"}


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> tuple[SeedPlace, ...]:
    """Load and validate the repository-owned seed catalog."""
    catalog_path = Path(path)
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read seed catalog {catalog_path}: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("seed catalog must be a non-empty JSON array")

    places: list[SeedPlace] = []
    seen_ids: set[UUID] = set()
    seen_names: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or set(item) != _SEED_FIELDS:
            raise ValueError(
                f"catalog row {index + 1} must contain exactly: "
                + ", ".join(sorted(_SEED_FIELDS))
            )
        try:
            place_id = UUID(item["id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"catalog row {index + 1} has an invalid UUID") from exc
        strings = ("name", "area", "category")
        if any(
            not isinstance(item[field], str) or not item[field].strip()
            for field in strings
        ):
            raise ValueError(f"catalog row {index + 1} has an empty required field")
        if item["category"] not in _PLACE_CATEGORIES:
            raise ValueError(f"catalog row {index + 1} has an unsupported category")
        for field in ("address", "description", "dog_access_rules"):
            if item[field] is not None and not isinstance(item[field], str):
                raise ValueError(
                    f"catalog row {index + 1} field {field} must be text or null"
                )
        facilities = item["facilities"]
        if not isinstance(facilities, list) or any(
            not isinstance(value, str) for value in facilities
        ):
            raise ValueError(
                f"catalog row {index + 1} facilities must be a string array"
            )
        if len(set(facilities)) != len(facilities):
            raise ValueError(f"catalog row {index + 1} facilities must be unique")
        if not isinstance(item["is_published"], bool):
            raise TypeError(f"catalog row {index + 1} is_published must be boolean")
        normalized_name = item["name"].casefold()
        if place_id in seen_ids or normalized_name in seen_names:
            raise ValueError(
                f"catalog contains duplicate ID or normalized name at row {index + 1}"
            )
        seen_ids.add(place_id)
        seen_names.add(normalized_name)
        places.append(
            SeedPlace(
                id=place_id,
                name=item["name"],
                category=item["category"],
                area=item["area"],
                address=item["address"],
                description=item["description"],
                dog_access_rules=item["dog_access_rules"],
                facilities=tuple(facilities),
                is_published=item["is_published"],
            )
        )
    return tuple(places)


_DSQL_APP_SCHEMA = "pawlocal"


def verify_dsql_app_schema(engine) -> None:
    """Fail closed if a DSQL seed would use a schema the API does not read."""
    if engine.dialect.name != "auroradsql":
        return
    with engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    if schema != _DSQL_APP_SCHEMA:
        raise RuntimeError(
            "Aurora DSQL seed aborted: runtime schema does not match the API schema"
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
        and record.category == seed.category
        and record.area == seed.area
        and record.address == seed.address
        and record.description == seed.description
        and record.dog_access_rules == seed.dog_access_rules
        and record.facilities == list(seed.facilities)
        and record.is_published == seed.is_published
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
    conflicting_ids = [row.id for row in by_name if row.id != seed.id]
    if conflicting_ids:
        existing_id = conflicting_ids[0]
        raise RuntimeError(
            f"seed name conflict for {seed.name}: catalog ID {seed.id} differs "
            f"from existing ID {existing_id}; review and migrate references explicitly"
        )
    if len(by_name) > 1:
        raise RuntimeError(f"multiple database records conflict with {seed.name}")
    return by_id


def seed_with_engine(
    engine,
    environment: str,
    *,
    confirm_production: bool = False,
    places: tuple[SeedPlace, ...] | None = None,
) -> list[str]:
    """Upsert catalog-owned fields by stable ID; never delete absent rows.

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

    places = places if places is not None else load_catalog()
    if not places:
        raise ValueError("seed catalog must not be empty")

    # Preflight every stable ID and normalized name before any write. A name
    # conflict still fails closed; only a matching stable ID is updateable.
    with SessionLocal() as session:
        for seed in places:
            _find_conflicts(session, seed)

    outcomes: list[str] = []
    for seed in places:
        with SessionLocal.begin() as session:
            existing = _find_conflicts(session, seed)
            if existing is None:
                session.add(
                    PlaceRecord(
                        id=seed.id,
                        name=seed.name,
                        category=seed.category,
                        area=seed.area,
                        address=seed.address,
                        description=seed.description,
                        dog_access_rules=seed.dog_access_rules,
                        facilities=list(seed.facilities),
                        is_published=seed.is_published,
                    )
                )
                outcomes.append(f"inserted {seed.name}")
            else:
                changed = not _matches(existing, seed)
                existing.name = seed.name
                existing.category = seed.category
                existing.area = seed.area
                existing.address = seed.address
                existing.description = seed.description
                existing.dog_access_rules = seed.dog_access_rules
                existing.facilities = list(seed.facilities)
                existing.is_published = seed.is_published
                outcomes.append(
                    ("updated " if changed else "already present ") + seed.name
                )

    # Read back the exact seeded records after all per-record transactions.
    with SessionLocal() as session:
        for seed in places:
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
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args(argv)

    try:
        from pawlocal.config import settings

        url = settings.sqlalchemy_url
        places = load_catalog(args.catalog)
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
            verify_dsql_app_schema(engine)
            for outcome in seed_with_engine(
                engine,
                args.environment,
                confirm_production=args.confirm_production,
                places=places,
            ):
                print(outcome)
        finally:
            engine.dispose()
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"seed aborted: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
