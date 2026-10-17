from datetime import UTC, datetime
from uuid import UUID

from pawlocal.infrastructure.models import ContributionRecord, PlaceRecord

PLACE_1 = UUID("00000000-0000-4000-8000-000000000001")
PLACE_2 = UUID("00000000-0000-4000-8000-000000000002")


def seed(session_factory):
    with session_factory() as session:
        session.add_all(
            [
                PlaceRecord(
                    id=PLACE_1,
                    name="Creekside Dog Park",
                    category="dog_park",
                    area="Brisbane City",
                    facilities=["Fenced", "Shade"],
                    is_published=True,
                ),
                PlaceRecord(
                    id=PLACE_2,
                    name="Coastal Walk",
                    category="walk",
                    area="Gold Coast",
                    facilities=["Shade"],
                    is_published=True,
                    dog_access_rules=None,
                ),
                PlaceRecord(
                    name="Private Draft",
                    category="beach",
                    area="Sunshine Coast",
                    facilities=[],
                    is_published=False,
                ),
            ]
        )
        session.commit()


def test_search_filters_paginates_and_excludes_unpublished(client, session_factory):
    seed(session_factory)
    response = client[0].get(
        "/api/v1/places",
        params=[
            ("facilities", "Shade"),
            ("area", "Brisbane City"),
            ("page", "1"),
            ("page_size", "1"),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(PLACE_1),
                "name": "Creekside Dog Park",
                "category": "dog_park",
                "area": "Brisbane City",
                "average_rating": None,
            }
        ],
        "page": 1,
        "page_size": 1,
        "total": 1,
    }


def test_search_empty_result_and_invalid_parameters(client, session_factory):
    seed(session_factory)
    empty = client[0].get("/api/v1/places", params={"q": "no match"})
    invalid = client[0].get("/api/v1/places", params={"category": "restaurant"})
    invalid_page = client[0].get("/api/v1/places", params={"page": "0"})
    invalid_facility = client[0].get(
        "/api/v1/places", params={"facilities": "Invented facility"}
    )

    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "bad_request"
    assert invalid_page.status_code == 400
    assert invalid_page.json()["code"] == "bad_request"
    assert invalid_facility.status_code == 400
    assert invalid_facility.json()["code"] == "bad_request"


def test_search_supports_text_category_and_page_boundaries(client, session_factory):
    seed(session_factory)
    app = client[0]
    search = app.get("/api/v1/places", params={"q": "Coastal", "category": "walk"})
    first_page = app.get("/api/v1/places", params={"page": "1", "page_size": "1"})
    second_page = app.get("/api/v1/places", params={"page": "2", "page_size": "1"})

    assert search.status_code == 200
    assert [item["name"] for item in search.json()["items"]] == ["Coastal Walk"]
    assert first_page.json()["total"] == 2
    assert len(first_page.json()["items"]) == 1
    assert len(second_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]


def test_detail_returns_unknown_facts_as_null_and_unknown_or_unpublished_is_404(
    client, session_factory
):
    seed(session_factory)
    found = client[0].get(f"/api/v1/places/{PLACE_2}")
    missing = client[0].get("/api/v1/places/00000000-0000-4000-8000-000000000099")
    invalid_id = client[0].get("/api/v1/places/not-a-uuid")

    assert found.status_code == 200
    assert found.json()["dog_access_rules"] is None
    assert found.json()["address"] is None
    assert found.json()["facilities"] == ["Shade"]
    assert missing.status_code == 404
    assert missing.json() == {"code": "not_found", "message": "Place not found"}
    assert invalid_id.status_code == 400


def test_reportable_contributions_are_paginated_and_exclude_private_identity(
    client, session_factory
):
    with session_factory() as session:
        session.add_all(
            [
                ContributionRecord(
                    id=UUID("00000000-0000-4000-8000-000000000011"),
                    kind="review",
                    body="A public review",
                    rating=4,
                    contributor_subject="private-subject-1",
                    is_published=True,
                    created_at=datetime(2026, 10, 18, 0, 0, tzinfo=UTC),
                ),
                ContributionRecord(
                    id=UUID("00000000-0000-4000-8000-000000000012"),
                    kind="tip",
                    body="Bring water",
                    contributor_subject="private-subject-2",
                    is_published=True,
                    created_at=datetime(2026, 10, 18, 0, 1, tzinfo=UTC),
                ),
                ContributionRecord(
                    kind="correction",
                    body="Not published",
                    contributor_subject="private-subject-3",
                    is_published=False,
                ),
            ]
        )
        session.commit()

    first = client[0].get(
        "/api/v1/contributions/reportable", params={"page": 1, "page_size": 1}
    )
    second = client[0].get(
        "/api/v1/contributions/reportable", params={"page": 2, "page_size": 1}
    )

    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert first.json()["items"][0]["body"] == "Bring water"
    assert set(first.json()["items"][0]) == {
        "id",
        "kind",
        "body",
        "place_id",
        "rating",
        "created_at",
    }
    assert second.json()["items"][0]["body"] == "A public review"
    assert "contributor_subject" not in first.text


def test_reportable_contributions_empty_and_invalid_paging(client):
    empty = client[0].get("/api/v1/contributions/reportable")
    invalid = client[0].get(
        "/api/v1/contributions/reportable", params={"page_size": 101}
    )

    assert empty.status_code == 200
    assert empty.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "bad_request"
