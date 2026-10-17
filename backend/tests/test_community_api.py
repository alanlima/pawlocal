from uuid import UUID

from pawlocal.api.auth import get_current_subject
from pawlocal.infrastructure.models import ContributionRecord, PlaceRecord, ReportRecord

PLACE_ID = UUID("00000000-0000-4000-8000-000000000021")


def seed_place(session_factory):
    with session_factory() as session:
        session.add(
            PlaceRecord(
                id=PLACE_ID,
                name="Test Park",
                category="dog_park",
                area="Brisbane City",
                facilities=[],
                is_published=True,
            )
        )
        session.commit()


def authenticate(client, subject="verified-user-subject"):
    client[0].app.dependency_overrides[get_current_subject] = lambda: subject


def test_anonymous_write_and_favourite_requests_require_authentication(client):
    app = client[0]
    favourites = app.get("/api/v1/me/favourites")
    contribution = app.post(
        "/api/v1/contributions", json={"kind": "tip", "body": "Bring water"}
    )
    report = app.post(
        "/api/v1/reports",
        json={
            "target_type": "place",
            "target_id": str(PLACE_ID),
            "reason": "Incorrect",
        },
    )

    assert (
        favourites.status_code == contribution.status_code == report.status_code == 401
    )
    assert favourites.json() == {
        "code": "unauthorized",
        "message": "Authentication required",
    }


def test_favourites_are_private_unique_and_idempotent(client, session_factory):
    seed_place(session_factory)
    app = client[0]
    authenticate(client)

    assert app.get("/api/v1/me/favourites").json() == []
    assert (
        app.put("/api/v1/me/favourites", json={"place_id": str(PLACE_ID)}).status_code
        == 204
    )
    assert (
        app.put("/api/v1/me/favourites", json={"place_id": str(PLACE_ID)}).status_code
        == 204
    )
    listed = app.get("/api/v1/me/favourites")
    assert listed.status_code == 200
    assert [place["id"] for place in listed.json()] == [str(PLACE_ID)]
    assert app.delete(f"/api/v1/me/favourites/{PLACE_ID}").status_code == 204
    assert app.delete(f"/api/v1/me/favourites/{PLACE_ID}").status_code == 204
    assert app.get("/api/v1/me/favourites").json() == []
    assert (
        app.put(
            "/api/v1/me/favourites",
            json={"place_id": "00000000-0000-4000-8000-000000000099"},
        ).status_code
        == 404
    )


def test_contribution_submission_duplicate_review_and_public_projection(
    client, session_factory
):
    seed_place(session_factory)
    app = client[0]
    authenticate(client)
    payload = {
        "kind": "review",
        "place_id": str(PLACE_ID),
        "rating": 5,
        "body": "A useful place review",
    }

    created = app.post("/api/v1/contributions", json=payload)
    duplicate = app.post("/api/v1/contributions", json=payload)
    public = app.get("/api/v1/contributions/reportable")

    assert created.status_code == 201
    assert set(created.json()) == {
        "id",
        "kind",
        "place_id",
        "rating",
        "body",
        "created_at",
    }
    assert duplicate.status_code == 409
    assert public.status_code == 200
    assert public.json()["items"][0]["body"] == "A useful place review"
    assert set(public.json()["items"][0]) == {
        "id",
        "kind",
        "body",
        "place_id",
        "rating",
        "created_at",
    }
    assert "verified-user-subject" not in public.text
    assert "contributor_subject" not in public.text
    with session_factory() as session:
        record = session.query(ContributionRecord).one()
        assert record.contributor_subject == "verified-user-subject"


def test_contribution_validation_rejects_client_identity_and_bad_values(client):
    app = client[0]
    authenticate(client)
    extra_identity = app.post(
        "/api/v1/contributions",
        json={"kind": "tip", "body": "A tip", "user_id": "attacker-selected"},
    )
    bad_rating = app.post(
        "/api/v1/contributions",
        json={"kind": "review", "rating": 6, "body": "Out of range"},
    )

    assert extra_identity.status_code == 400
    assert bad_rating.status_code == 400


def test_reports_are_accepted_without_echoing_reporter_identity(
    client, session_factory
):
    seed_place(session_factory)
    app = client[0]
    authenticate(client)

    accepted = app.post(
        "/api/v1/reports",
        json={
            "target_type": "place",
            "target_id": str(PLACE_ID),
            "reason": "Access changed",
        },
    )
    missing = app.post(
        "/api/v1/reports",
        json={
            "target_type": "place",
            "target_id": "00000000-0000-4000-8000-000000000099",
            "reason": "Unlisted place",
        },
    )

    assert accepted.status_code == 202
    assert accepted.content == b""
    assert missing.status_code == 400
    with session_factory() as session:
        report = session.query(ReportRecord).one()
        assert report.reporter_subject == "verified-user-subject"
