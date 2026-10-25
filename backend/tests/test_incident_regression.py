from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord

RATED_PLACE_ID = UUID("00000000-0000-4000-8000-000000000201")
UNRATED_PLACE_ID = UUID("00000000-0000-4000-8000-000000000202")


def seed(session_factory):
    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=RATED_PLACE_ID,
                    name="Rated Harbour Walk",
                    category="walk",
                    area="Brisbane City",
                    facilities=["Shade"],
                    average_rating=4.8,
                    is_published=True,
                ),
                PlaceRecord(
                    id=UNRATED_PLACE_ID,
                    name="Unrated River Park",
                    category="dog_park",
                    area="Brisbane City",
                    facilities=[],
                    average_rating=None,
                    is_published=True,
                ),
            ]
        )
        session.commit()


def test_search_and_detail_handle_mixed_rating_values(client, session_factory):
    seed(session_factory)

    search_response = client[0].get("/api/v1/places", params={"q": "Brisbane"})
    detail_response = client[0].get(f"/api/v1/places/{UNRATED_PLACE_ID}")

    assert search_response.status_code == 200
    assert [item["id"] for item in search_response.json()["items"]] == [
        str(RATED_PLACE_ID),
        str(UNRATED_PLACE_ID),
    ]
    assert search_response.json()["items"][1]["average_rating"] is None

    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == str(UNRATED_PLACE_ID)
    assert detail_response.json()["average_rating"] is None
    assert detail_response.json()["facilities"] == []
