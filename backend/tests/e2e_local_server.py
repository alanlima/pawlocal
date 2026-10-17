"""Test-only API and ephemeral JWKS issuer for the browser integration suite.

Run only in the dedicated local test container. This is not imported by the API
application and never changes production token validation behavior.
"""

import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
import uvicorn
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import delete

API_PORT = int(os.environ.get("PAWLOCAL_E2E_API_PORT", "18001"))
ISSUER_PORT = int(os.environ.get("PAWLOCAL_E2E_ISSUER_PORT", "18002"))
ISSUER = f"http://127.0.0.1:{ISSUER_PORT}"
CLIENT_ID = "pawlocal-e2e-client"
SUBJECT = "pawlocal-browser-e2e-subject"
PLACE_ID = UUID("00000000-0000-4000-8000-000000000991")
KEY_ID = "pawlocal-local-e2e-key"


def prepare_test_environment() -> None:
    os.environ["PAWLOCAL_DATABASE_URL"] = os.environ.get(
        "PAWLOCAL_DATABASE_URL",
        "postgresql+psycopg://pawlocal:pawlocal-local@172.17.0.2:5432/pawlocal_stage3_verify",
    )
    os.environ["PAWLOCAL_COGNITO_ISSUER"] = ISSUER
    os.environ["PAWLOCAL_COGNITO_APP_CLIENT_ID"] = CLIENT_ID
    os.chdir(Path(__file__).resolve().parents[1])
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["PAWLOCAL_DATABASE_URL"])
    command.upgrade(config, "head")


prepare_test_environment()

from pawlocal.infrastructure.database import SessionLocal
from pawlocal.infrastructure.models import (
    ContributionRecord,
    FavouriteRecord,
    PlaceRecord,
    ReportRecord,
)
from pawlocal.main import app as api_app

private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})

issuer_app = FastAPI()


@issuer_app.get("/.well-known/jwks.json")
def jwks() -> dict[str, list[dict[str, str]]]:
    return {"keys": [jwk]}


@issuer_app.get("/test-access-token")
def access_token() -> dict[str, str]:
    now = datetime.now(UTC)
    encoded = jwt.encode(
        {
            "iss": ISSUER,
            "sub": SUBJECT,
            "token_use": "access",
            "client_id": CLIENT_ID,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )
    return {"access_token": encoded, "subject": SUBJECT}


def reset_synthetic_data() -> None:
    with SessionLocal.begin() as session:
        session.execute(
            delete(ReportRecord).where(ReportRecord.reporter_subject == SUBJECT)
        )
        session.execute(
            delete(FavouriteRecord).where(FavouriteRecord.user_subject == SUBJECT)
        )
        session.execute(
            delete(ContributionRecord).where(
                ContributionRecord.contributor_subject == SUBJECT
            )
        )
        session.execute(delete(PlaceRecord).where(PlaceRecord.id == PLACE_ID))
        session.add(
            PlaceRecord(
                id=PLACE_ID,
                name="Synthetic Stage 3 E2E Dog Park",
                category="dog_park",
                area="Brisbane City",
                address=None,
                description="Synthetic local test fixture.",
                dog_access_rules=None,
                facilities=["Fenced"],
                is_published=True,
            )
        )


reset_synthetic_data()

threading.Thread(
    target=uvicorn.run,
    kwargs={
        "app": issuer_app,
        "host": "0.0.0.0",
        "port": ISSUER_PORT,
        "log_level": "warning",
    },
    daemon=True,
).start()
uvicorn.run(api_app, host="0.0.0.0", port=API_PORT, log_level="warning")
