from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord


def test_search_and_detail_handle_unrated_places_without_failing(client, session_factory):
    first_place = UUID("00000000-0000-4000-8000-0000000000a1")
    second_place = UUID("00000000-0000-4000-8000-0000000000a2")
    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=second_place,
                    name="Zeta Dog Park",
                    category="dog_park",
                    area="Brisbane City",
                    facilities=[],
                    is_published=True,
                ),
                PlaceRecord(
                    id=first_place,
                    name="Alpha Dog Park",
                    category="dog_park",
                    area="Brisbane City",
                    facilities=[],
                    is_published=True,
                ),
            ]
        )
        session.commit()

    search_response = client[0].get("/api/v1/places")
    detail_response = client[0].get(f"/api/v1/places/{first_place}")

    assert search_response.status_code == 200
    assert [item["name"] for item in search_response.json()["items"]] == [
        "Alpha Dog Park",
        "Zeta Dog Park",
    ]
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "Alpha Dog Park"
