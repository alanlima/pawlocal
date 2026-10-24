from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord

UNRATED_PLACE_ID = UUID("00000000-0000-4000-8000-0000000000a1")
RATED_PLACE_ID = UUID("00000000-0000-4000-8000-0000000000a2")


def test_search_and_detail_survive_unrated_places(client):
    test_client, session_factory = client

    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=UNRATED_PLACE_ID,
                    name='Incident Unrated Park',
                    category='dog_park',
                    area='Brisbane',
                    is_published=True,
                ),
                PlaceRecord(
                    id=RATED_PLACE_ID,
                    name='Incident Rated Park',
                    category='dog_park',
                    area='Brisbane',
                    is_published=True,
                    average_rating=4.7,
                    description='A place with a community rating.',
                ),
            ]
        )
        session.commit()

    response = test_client.get("/api/v1/places")
    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 2
    assert [item["id"] for item in payload["items"]] == [
        str(RATED_PLACE_ID),
        str(UNRATED_PLACE_ID),
    ]

    detail_response = test_client.get(f"/api/v1/places/{UNRATED_PLACE_ID}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == str(UNRATED_PLACE_ID)
    assert detail["average_rating"] is None
