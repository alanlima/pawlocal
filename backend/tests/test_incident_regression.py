from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord


def test_search_ranks_rated_places_without_failing_on_unrated_places(
    client, session_factory
):
    rated_place_id = UUID("00000000-0000-4000-8000-000000000041")
    unrated_place_id = UUID("00000000-0000-4000-8000-000000000042")

    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=unrated_place_id,
                    name="Unrated Creek Walk",
                    category="walk",
                    area="Brisbane City",
                    facilities=[],
                    average_rating=None,
                    is_published=True,
                ),
                PlaceRecord(
                    id=rated_place_id,
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

    response = client[0].get("/api/v1/places")
    detail = client[0].get(f"/api/v1/places/{rated_place_id}")

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert [item["id"] for item in response.json()["items"]] == [
        str(rated_place_id),
        str(unrated_place_id),
    ]
    assert detail.status_code == 200
    assert detail.json()["average_rating"] == 4.5
