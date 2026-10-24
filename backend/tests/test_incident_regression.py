from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord


PLACE_WITH_RATING = UUID("00000000-0000-4000-8000-000000000201")
PLACE_WITHOUT_RATING = UUID("00000000-0000-4000-8000-000000000202")


def test_search_and_detail_survive_places_without_average_ratings(client, session_factory):
    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=PLACE_WITHOUT_RATING,
                    name="Unrated Creek Walk",
                    category="walk",
                    area="Brisbane City",
                    facilities=[],
                    is_published=True,
                ),
                PlaceRecord(
                    id=PLACE_WITH_RATING,
                    name="Rated River Park",
                    category="dog_park",
                    area="Brisbane City",
                    facilities=["Shade"],
                    average_rating=4.6,
                    is_published=True,
                ),
            ]
        )
        session.commit()

    response = client[0].get("/api/v1/places", params={"page": 1, "page_size": 20})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        str(PLACE_WITH_RATING),
        str(PLACE_WITHOUT_RATING),
    ]

    detail = client[0].get(f"/api/v1/places/{PLACE_WITH_RATING}")

    assert detail.status_code == 200
    assert detail.json()["name"] == "Rated River Park"
    assert detail.json()["facilities"] == ["Shade"]
