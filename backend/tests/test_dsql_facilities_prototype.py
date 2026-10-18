from uuid import UUID

import pytest
from sqlalchemy import create_engine, delete, insert
from sqlalchemy.exc import NoSuchModuleError

from pawlocal.dsql_facilities_prototype import (
    build_place_search,
    facility_rows_from_existing,
    metadata,
    place_facilities,
    places,
    validate_requested_facilities,
)

PLACE_ALPHA = UUID("00000000-0000-4000-8000-000000000001")
PLACE_BETA = UUID("00000000-0000-4000-8000-000000000002")
PLACE_CHARLIE = UUID("00000000-0000-4000-8000-000000000003")
PLACE_DRAFT = UUID("00000000-0000-4000-8000-000000000004")


@pytest.fixture
def connection():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(places),
            [
                {"id": PLACE_ALPHA, "name": "Alpha Park", "is_published": True},
                {"id": PLACE_BETA, "name": "Beta Park", "is_published": True},
                {
                    "id": PLACE_CHARLIE,
                    "name": "Charlie Walk",
                    "is_published": True,
                },
                {"id": PLACE_DRAFT, "name": "Draft Place", "is_published": False},
            ],
        )
        conn.execute(
            insert(place_facilities),
            facility_rows_from_existing(
                [
                    (PLACE_ALPHA, ["Fenced", "Shade"]),
                    # Duplicate stored values are retained in ordinal order;
                    # EXISTS still returns the place once.
                    (PLACE_BETA, ["Fenced", "Fenced", "Shade"]),
                    (PLACE_CHARLIE, ["Shade"]),
                    (PLACE_DRAFT, ["Fenced", "Shade"]),
                ]
            ),
        )
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        engine.dispose()


def _search(connection, facilities, page=1, page_size=20):
    page_statement, count_statement = build_place_search(
        facilities=facilities, page=page, page_size=page_size
    )
    result = connection.execute(page_statement).mappings().all()
    total = connection.scalar(count_statement)
    return result, total


def test_empty_facility_filter_keeps_all_published_places_and_stable_paging(connection):
    first_page, total = _search(connection, [], page=1, page_size=2)
    second_page, second_total = _search(connection, [], page=2, page_size=2)

    assert [row["name"] for row in first_page] == ["Alpha Park", "Beta Park"]
    assert [row["name"] for row in second_page] == ["Charlie Walk"]
    assert total == second_total == 3


def test_same_name_order_uses_uuid_tiebreaker_across_page_boundary():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    lower_id = UUID("00000000-0000-4000-8000-000000000005")
    higher_id = UUID("00000000-0000-4000-8000-000000000006")
    with engine.begin() as conn:
        conn.execute(delete(place_facilities))
        conn.execute(delete(places))
        # Insert in reverse UUID order; query order must use name then id.
        conn.execute(
            insert(places),
            [
                {"id": higher_id, "name": "Twin Park", "is_published": True},
                {"id": lower_id, "name": "Twin Park", "is_published": True},
            ],
        )

    try:
        with engine.connect() as conn:
            first_page, total = _search(conn, [], page=1, page_size=1)
            second_page, second_total = _search(conn, [], page=2, page_size=1)
        assert [row["id"] for row in first_page] == [lower_id]
        assert [row["id"] for row in second_page] == [higher_id]
        assert total == second_total == 2
    finally:
        engine.dispose()


def test_single_facility_filter_matches_any_place_with_that_facility(connection):
    result, total = _search(connection, ["Shade"])

    assert [row["name"] for row in result] == [
        "Alpha Park",
        "Beta Park",
        "Charlie Walk",
    ]
    assert total == 3


def test_multiple_facilities_use_and_semantics_without_duplicate_places(connection):
    result, total = _search(connection, ["Fenced", "Shade"])

    assert [row["name"] for row in result] == ["Alpha Park", "Beta Park"]
    assert total == 2
    assert len({row["id"] for row in result}) == len(result)


def test_repeated_requested_facility_does_not_change_and_semantics(connection):
    result, total = _search(connection, ["Fenced", "Fenced"])

    assert [row["name"] for row in result] == ["Alpha Park", "Beta Park"]
    assert total == 2


def test_validation_and_fixture_conversion_reject_unknown_facilities():
    with pytest.raises(ValueError, match="Unsupported place facilities"):
        validate_requested_facilities(["invented"])
    with pytest.raises(ValueError, match="Unsupported place facilities"):
        facility_rows_from_existing([(PLACE_ALPHA, ["invented"])])


def test_fixture_conversion_preserves_array_order_and_duplicate_values():
    rows = facility_rows_from_existing(
        [(PLACE_BETA, ["Fenced", "Fenced", "Shade"])]
    )

    assert rows == [
        {"place_id": PLACE_BETA, "ordinal": 0, "facility": "Fenced"},
        {"place_id": PLACE_BETA, "ordinal": 1, "facility": "Fenced"},
        {"place_id": PLACE_BETA, "ordinal": 2, "facility": "Shade"},
    ]


def test_generated_dsql_sql_has_no_array_storage_or_operator():
    from scripts.render_dsql_facilities_prototype import render_sql

    try:
        sql = render_sql()
    except NoSuchModuleError:
        pytest.skip("install the optional dsql-prototype dependencies")

    lowered = sql.lower()
    assert "create table places" in lowered
    assert "create table place_facilities" in lowered
    assert lowered.count("exists (select 1") >= 2
    assert "array" not in lowered
    assert " any(" not in lowered
    assert "identity" not in lowered
    assert "facility_0" in lowered
    assert "facility_1" in lowered
