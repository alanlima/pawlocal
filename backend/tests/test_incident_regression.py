from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord

RATED_PLACE_ID = UUID("00000000-0000-4000-8000-000000000041")
UNRATED_PLACE_ID = UUID("00000000-0000-4000-8000-000000000042")


def test_search_and_detail_handle_mixed_average_ratings(client, session_factory):
    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=UNRATED_PLACE_ID,
                    name="Unrated Creek Walk",
                    category="walk",
                    area="Brisbane City",
                    facilities=[],
                    is_published=True,
                ),
                PlaceRecord(
                    id=RATED_PLACE_ID,
                    name="Rated Creek Walk",
                    category="walk",
                    area="Brisbane City",
                    facilities=[],
                    average_rating=4.5,
                    is_published=True,
                ),
            ]
        )
        session.commit()

    search = client[0].get("/api/v1/places")
    detail = client[0].get(f"/api/v1/places/{UNRATED_PLACE_ID}")

    assert search.status_code == 200
    assert [item["id"] for item in search.json()["items"]] == [
        str(RATED_PLACE_ID),
        str(UNRATED_PLACE_ID),
    ]
    assert detail.status_code == 200
    assert detail.json()["average_rating"] is None
