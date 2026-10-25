from datetime import UTC, datetime
from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord

PLACE_HIGH = UUID('00000000-0000-4000-8000-000000000041')
PLACE_LOW = UUID('00000000-0000-4000-8000-000000000042')
PLACE_UNRATED = UUID('00000000-0000-4000-8000-000000000043')


def test_search_keeps_unrated_places_but_sorts_rated_places_first(client, session_factory):
    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=PLACE_LOW,
                    name='Low Rated Walk',
                    category='walk',
                    area='Brisbane City',
                    average_rating=2.5,
                    facilities=[],
                    is_published=True,
                    source_updated_at=datetime(2026, 10, 1, tzinfo=UTC),
                ),
                PlaceRecord(
                    id=PLACE_HIGH,
                    name='Top Rated Park',
                    category='dog_park',
                    area='Brisbane City',
                    average_rating=4.8,
                    facilities=[],
                    is_published=True,
                    source_updated_at=datetime(2026, 10, 2, tzinfo=UTC),
                ),
                PlaceRecord(
                    id=PLACE_UNRATED,
                    name='Unrated Beach',
                    category='beach',
                    area='Gold Coast',
                    average_rating=None,
                    facilities=[],
                    is_published=True,
                    source_updated_at=datetime(2026, 10, 3, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

    response = client[0].get('/api/v1/places')

    assert response.status_code == 200
    assert [item['id'] for item in response.json()['items']] == [
        str(PLACE_HIGH),
        str(PLACE_LOW),
        str(PLACE_UNRATED),
    ]


def test_search_orders_by_rating_before_page_boundaries_and_keeps_detail_fields(
    client,
    session_factory,
):
    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=PLACE_LOW,
                    name='Alpha Walk',
                    category='walk',
                    area='Brisbane City',
                    description='Low-rated but published.',
                    dog_access_rules='Keep dogs on lead near the creek.',
                    facilities=['Shade'],
                    average_rating=2.5,
                    is_published=True,
                    source_updated_at=datetime(2026, 10, 1, tzinfo=UTC),
                ),
                PlaceRecord(
                    id=PLACE_HIGH,
                    name='Bravo Park',
                    category='dog_park',
                    area='Brisbane City',
                    description='The highest rated place on this page.',
                    dog_access_rules='Off-leash area inside the fenced boundary.',
                    facilities=['Fenced', 'Drinking water'],
                    average_rating=4.8,
                    is_published=True,
                    source_updated_at=datetime(2026, 10, 2, tzinfo=UTC),
                ),
                PlaceRecord(
                    id=PLACE_UNRATED,
                    name='Charlie Beach',
                    category='beach',
                    area='Gold Coast',
                    description='Still awaiting community feedback.',
                    dog_access_rules=None,
                    facilities=[],
                    average_rating=None,
                    is_published=True,
                    source_updated_at=datetime(2026, 10, 3, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

    search = client[0].get('/api/v1/places', params={'page_size': '1'})
    detail = client[0].get(f'/api/v1/places/{PLACE_HIGH}')

    assert search.status_code == 200
    assert search.json()['items'][0]['id'] == str(PLACE_HIGH)
    assert detail.status_code == 200
    assert detail.json()['id'] == str(PLACE_HIGH)
    assert detail.json()['description'] == 'The highest rated place on this page.'
    assert detail.json()['dog_access_rules'] == 'Off-leash area inside the fenced boundary.'
    assert detail.json()['facilities'] == ['Fenced', 'Drinking water']
