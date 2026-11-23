from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base, get_db
from app.security import login_throttle


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def settings():
    return main.get_settings().model_copy(
        update={
            "top_k": 5,
            "anthropic_api_key": "test-key",
            "sam_gov_api_key": "sam-key",
            "smtp_host": None,
            "smtp_from": None,
            "allow_signup": True,
        }
    )


@pytest.fixture
def make_client(session_factory, settings):
    """Return a factory for independent browser-like clients sharing one test database."""

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override_db
    login_throttle._failures.clear()
    clients: list[TestClient] = []
    with (
        patch.object(main, "init_db"),
        patch.object(main, "get_settings", return_value=settings),
    ):

        def factory() -> TestClient:
            client = TestClient(main.app, headers={"X-Requested-With": "tender-matcher"})
            client.__enter__()
            clients.append(client)
            return client

        yield factory
        for client in clients:
            client.__exit__(None, None, None)
    main.app.dependency_overrides.pop(get_db, None)


def sign_up(client: TestClient, company="Acme IT", email="owner@acme.test"):
    response = client.post(
        "/api/auth/signup",
        json={"company_name": company, "email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201, response.text
    return response.json()


PROFILE = {"services": ["cloud migration"], "contract_size_usd": {"min": 1000, "max": 100000}}


@pytest.fixture
def client(make_client):
    """A signed-in client whose company has a saved profile."""
    client = make_client()
    sign_up(client)
    assert client.put("/api/profile", json=PROFILE).status_code == 200
    return client
