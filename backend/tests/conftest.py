import pytest
from fastapi.testclient import TestClient
from pawlocal.api.rate_limit import write_rate_limiter
from pawlocal.infrastructure import models  # noqa: F401
from pawlocal.infrastructure.database import Base, get_session
from pawlocal.main import app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client():
    write_rate_limiter.reset()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, TestingSession
    app.dependency_overrides.clear()
    write_rate_limiter.reset()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session_factory(client):
    return client[1]
