from uuid import uuid4

from sqlalchemy import event

from pawlocal.infrastructure.community import CommunityRepository
from pawlocal.infrastructure.models import FavouriteRecord, PlaceRecord
from pawlocal.infrastructure.places import SqlAlchemyPlaceRepository


def _seed_places(session_factory, count=6):
    with session_factory() as session:
        place_ids = []
        for index in range(count):
            place_id = uuid4()
            place_ids.append(place_id)
            session.add(
                PlaceRecord(
                    id=place_id,
                    name=f"Park {index:02}",
                    category="dog_park",
                    area="Brisbane City",
                    facilities=["Fenced", "Shade"],
                    is_published=True,
                )
            )
        session.flush()
        for place_id in place_ids:
            session.add(
                FavouriteRecord(user_subject="reader", place_id=place_id)
            )
        session.commit()


def _run_and_count_facility_loader_queries(session, operation):
    statements = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = statement.lower().replace('"', "")
        if (
            "from place_facilities" in normalized
            and "where place_facilities.place_id in" in normalized
        ):
            statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        result = operation()
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)
    return result, len(statements)


def test_place_discovery_loads_facilities_in_one_batch(session_factory):
    _seed_places(session_factory)
    with session_factory() as session:
        places, facility_query_count = _run_and_count_facility_loader_queries(
            session,
            lambda: SqlAlchemyPlaceRepository(session).search(
                query=None,
                area=None,
                category=None,
                facilities=[],
                page=1,
                page_size=20,
            )[0],
        )

    assert len(places) == 6
    assert all(place.facilities == ("Fenced", "Shade") for place in places)
    assert facility_query_count == 1


def test_favourites_load_facilities_in_one_batch(session_factory):
    _seed_places(session_factory)
    with session_factory() as session:
        places, facility_query_count = _run_and_count_facility_loader_queries(
            session, lambda: CommunityRepository(session).list_favourites("reader")
        )

    assert len(places) == 6
    assert all(place.facilities == ("Fenced", "Shade") for place in places)
    assert facility_query_count == 1
