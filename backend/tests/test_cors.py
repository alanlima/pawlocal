from fastapi import FastAPI
from fastapi.testclient import TestClient

from pawlocal.main import add_cors_middleware


def test_cors_allows_only_the_configured_frontend_origin():
    app = FastAPI()
    app.add_api_route("/api/v1/places", lambda: {"places": []}, methods=["GET"])
    add_cors_middleware(app, ["https://pawlocal.example.test"])
    client = TestClient(app)

    allowed = client.options(
        "/api/v1/places",
        headers={
            "Origin": "https://pawlocal.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://pawlocal.example.test"
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()

    denied = client.options(
        "/api/v1/places",
        headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


def test_health_exposes_nonsecret_release_identity(client, monkeypatch):
    from pawlocal.config import settings

    monkeypatch.setattr(settings, "release_environment", "development")
    monkeypatch.setattr(settings, "release_image_digest", "sha256:" + "a" * 64)

    response = client[0].get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
        "image_digest": "sha256:" + "a" * 64,
    }
