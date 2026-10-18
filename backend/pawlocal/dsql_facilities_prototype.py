"""Offline-only candidate schema and query for DSQL facility filters.

This module is deliberately not imported by the API or the production database
configuration. It is a compatibility prototype, not a supported runtime adapter.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    bindparam,
    func,
    select,
)
from sqlalchemy.sql import Select

from pawlocal.domain.places import PLACE_FACILITIES

metadata = MetaData()

# Only the place columns needed by this facilities-only prototype are declared.
# This is not a complete DSQL replacement for the production places table.
places = Table(
    "places",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("is_published", Boolean, nullable=False),
)

_facility_literals = ", ".join(
    "'" + facility.replace("'", "''") + "'" for facility in sorted(PLACE_FACILITIES)
)
place_facilities = Table(
    "place_facilities",
    metadata,
    Column(
        "place_id",
        Uuid(as_uuid=True),
        ForeignKey("places.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Retaining an ordinal preserves the existing array's order and even
    # duplicate values when a fixture is converted. Search uses EXISTS, so
    # these rows cannot multiply a place in the result set.
    Column("ordinal", Integer, primary_key=True, autoincrement=False),
    Column("facility", String(80), nullable=False),
    CheckConstraint("ordinal >= 0", name="ck_place_facilities_ordinal"),
    CheckConstraint(
        f"facility IN ({_facility_literals})", name="ck_place_facilities_value"
    ),
)
Index(
    "ix_place_facilities_facility_place",
    place_facilities.c.facility,
    place_facilities.c.place_id,
)


def validate_requested_facilities(facilities: Iterable[str]) -> tuple[str, ...]:
    """Validate filter values and collapse repeats without changing AND meaning."""
    requested = tuple(dict.fromkeys(facilities))
    unknown = set(requested) - PLACE_FACILITIES
    if unknown:
        raise ValueError(f"Unsupported place facilities: {sorted(unknown)}")
    return requested


def facility_rows_from_existing(
    places_with_facilities: Iterable[tuple[Any, Iterable[str]]],
) -> list[dict[str, Any]]:
    """Convert existing `(place_id, facilities[])` fixtures to ordered rows."""
    rows: list[dict[str, Any]] = []
    for place_id, facilities in places_with_facilities:
        for ordinal, facility in enumerate(facilities):
            validate_requested_facilities([facility])
            rows.append(
                {"place_id": place_id, "ordinal": ordinal, "facility": facility}
            )
    return rows


def build_place_search(
    *, facilities: Iterable[str], page: int, page_size: int
) -> tuple[Select, Select]:
    """Build a paged published-place query and its exact count query.

    Each distinct selected facility gets its own correlated EXISTS predicate,
    preserving the current API's all-selected (AND) behavior without a join
    that could duplicate places.
    """
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")

    requested = validate_requested_facilities(facilities)
    predicates = [places.c.is_published.is_(True)]
    for index, facility in enumerate(requested):
        match = (
            select(1)
            .select_from(place_facilities)
            .where(
                place_facilities.c.place_id == places.c.id,
                place_facilities.c.facility == bindparam(
                    f"facility_{index}", value=facility
                ),
            )
            .correlate(places)
            .exists()
        )
        predicates.append(match)

    statement = select(places).where(*predicates)
    count_statement = select(func.count()).select_from(places).where(*predicates)
    page_statement = (
        statement.order_by(places.c.name, places.c.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return page_statement, count_statement
