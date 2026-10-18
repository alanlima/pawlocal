from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from pawlocal.config import settings

bearer_scheme = HTTPBearer(scheme_name="bearerAuth", auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "unauthorized", "message": "Authentication required"},
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300)


def get_current_subject(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    issuer = settings.cognito_issuer
    client_id = settings.cognito_app_client_id
    if not issuer or not client_id:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "service_unavailable",
                "message": "Identity validation is not configured",
            },
        )
    jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(
            credentials.credentials
        )
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False, "require": ["exp"]},
        )
    except (jwt.PyJWTError, OSError, ValueError):
        raise _unauthorized() from None

    if claims.get("token_use") != "access" or claims.get("client_id") != client_id:
        raise _unauthorized()
    audience = claims.get("aud")
    expected_audience = settings.cognito_resource_audience
    if settings.cognito_require_resource_audience and not expected_audience:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "service_unavailable",
                "message": "Token audience validation is not configured",
            },
        )
    audience_matches = audience == expected_audience or (
        isinstance(audience, list) and expected_audience in audience
    )
    if settings.cognito_require_resource_audience and not audience_matches:
        raise _unauthorized()
    if audience is not None and not audience_matches:
        raise _unauthorized()

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise _unauthorized()
    return subject
