from datetime import UTC, datetime
from uuid import UUID

from pawlocal.infrastructure.models import PlaceRecord

HIKING_PLACE = UUID('00000000-0000-4000-8000-000000000044')


def test_hiking_area_search_and_detail_remain_available(client, session_factory):
    with session_factory() as session:
        session.add(
            PlaceRecord(
                id=HIKING_PLACE,
                name='Mt Coot-tha Trails',
                category='hiking_area',
                area='Brisbane City',
                description='Bushwalking trails with dog access.',
                dog_access_rules='Dogs must stay on lead on shared trails.',
                facilities=['Shade'],
                average_rating=4.4,
                is_published=True,
                source_updated_at=datetime(2026, 10, 25, tzinfo=UTC),
            )
        )
        session.commit()

    search_response = client[0].get('/api/v1/places', params={'category': 'hiking_area'})
    detail_response = client[0].get(f'/api/v1/places/{HIKING_PLACE}')

    assert search_response.status_code == 200
    assert search_response.json()['total'] == 1
    assert search_response.json()['items'][0]['id'] == str(HIKING_PLACE)
    assert detail_response.status_code == 200
    assert detail_response.json()['id'] == str(HIKING_PLACE)
    assert detail_response.json()['category'] == 'hiking_area'
    assert detail_response.json()['facilities'] == ['Shade']
