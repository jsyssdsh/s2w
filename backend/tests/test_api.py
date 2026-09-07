from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def client(seeded_session_factory: sessionmaker) -> TestClient:
    from app.db import get_session
    from app.main import app

    def override() -> Session:
        with seeded_session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_regions(client: TestClient) -> None:
    response = client.get("/api/regions")
    assert response.status_code == 200
    names = [r["name"] for r in response.json()]
    assert "충남 논산시" in names


def test_crops(client: TestClient) -> None:
    response = client.get("/api/crops")
    assert response.status_code == 200
    assert {c["name"] for c in response.json()} >= {"토마토", "양파"}


def test_unknown_api_path_is_404(client: TestClient) -> None:
    assert client.get("/api/does-not-exist").status_code == 404
