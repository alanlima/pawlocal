from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pawlocal.api import auth
from pawlocal.config import settings


@pytest.fixture
def jwt_keys(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    issuer = "https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_test"
    client_id = "test-app-client"
    monkeypatch.setattr(settings, "cognito_issuer", issuer)
    monkeypatch.setattr(settings, "cognito_app_client_id", client_id)
    monkeypatch.setattr(settings, "cognito_resource_audience", None)
    monkeypatch.setattr(settings, "cognito_require_resource_audience", False)
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=public_key)
        ),
    )
    return private_key, issuer, client_id


def token(private_key, **overrides):
    now = datetime.now(UTC)
    claims = {
        "iss": "https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_test",
        "sub": "user-subject-123",
        "token_use": "access",
        "client_id": "test-app-client",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


def credentials(encoded):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=encoded)


def test_access_token_validates_signature_issuer_and_access_token_claims(jwt_keys):
    private_key, _, _ = jwt_keys
    assert (
        auth.get_current_subject(credentials(token(private_key))) == "user-subject-123"
    )


@pytest.mark.parametrize(
    "claims",
    [
        {"token_use": "id"},
        {"client_id": "another-app-client"},
        {"iss": "https://wrong-issuer.example"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"sub": ""},
    ],
)
def test_invalid_access_token_claims_are_rejected(jwt_keys, claims):
    private_key, _, _ = jwt_keys
    with pytest.raises(HTTPException) as error:
        auth.get_current_subject(credentials(token(private_key, **claims)))
    assert error.value.status_code == 401


def test_missing_token_is_unauthorized_even_if_auth_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "cognito_issuer", None)
    monkeypatch.setattr(settings, "cognito_app_client_id", None)
    with pytest.raises(HTTPException) as error:
        auth.get_current_subject(None)
    assert error.value.status_code == 401


def test_audience_is_checked_when_present_and_required_when_configured(
    jwt_keys, monkeypatch
):
    private_key, _, _ = jwt_keys
    monkeypatch.setattr(settings, "cognito_resource_audience", "pawlocal-api")
    assert (
        auth.get_current_subject(credentials(token(private_key, aud="pawlocal-api")))
        == "user-subject-123"
    )
    with pytest.raises(HTTPException) as wrong_audience:
        auth.get_current_subject(credentials(token(private_key, aud="another-api")))
    assert wrong_audience.value.status_code == 401

    monkeypatch.setattr(settings, "cognito_require_resource_audience", True)
    with pytest.raises(HTTPException) as missing_audience:
        auth.get_current_subject(credentials(token(private_key)))
    assert missing_audience.value.status_code == 401
