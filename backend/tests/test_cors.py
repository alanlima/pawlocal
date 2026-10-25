import pytest
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
    assert (
        allowed.headers["access-control-allow-origin"]
        == "https://pawlocal.example.test"
    )
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()

    denied = client.options(
        "/api/v1/places",
        headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health_exposes_nonsecret_release_identity(client, monkeypatch, path):
    from pawlocal.config import settings

    monkeypatch.setattr(settings, "release_environment", "development")
    monkeypatch.setattr(settings, "release_image_digest", "sha256:" + "a" * 64)

    response = client[0].get(path)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "telemetry_enabled": False,
        "environment": "development",
        "image_digest": "sha256:" + "a" * 64,
    }


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health_retains_configured_cors_policy(path):
    from pawlocal.main import health

    app = FastAPI()
    app.add_api_route(path, health, methods=["GET"])
    add_cors_middleware(app, ["https://pawlocal.example.test"])
    with TestClient(app) as client:
        allowed = client.get(path, headers={"Origin": "https://pawlocal.example.test"})
        denied = client.get(path, headers={"Origin": "https://untrusted.example.test"})

    assert allowed.status_code == denied.status_code == 200
    assert (
        allowed.headers["access-control-allow-origin"]
        == "https://pawlocal.example.test"
    )
    assert "access-control-allow-origin" not in denied.headers


def test_public_health_is_unversioned_and_shares_internal_handler():
    from pawlocal.main import app, health

    endpoints = {
        route.path: route.endpoint
        for route in app.routes
        if getattr(route, "path", None) in {"/health", "/api/health"}
    }
    assert endpoints == {"/health": health, "/api/health": health}
