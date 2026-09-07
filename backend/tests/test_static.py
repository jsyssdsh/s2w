"""The container serves the exported frontend from the same process as the API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def static_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    static_dir = tmp_path / "static"
    (static_dir / "_next").mkdir(parents=True)
    (static_dir / "index.html").write_text("<title>울퉁불퉁 농장 AI</title>", encoding="utf-8")
    (static_dir / "map").mkdir()
    (static_dir / "map" / "index.html").write_text("map", encoding="utf-8")

    monkeypatch.setenv("STATIC_DIR", str(static_dir))
    monkeypatch.setenv("SEED_ON_START", "false")

    from fastapi import FastAPI

    from app.config import get_settings
    from app.main import _mount_frontend
    from app.routers import include_all

    get_settings.cache_clear()
    app = FastAPI()
    include_all(app)
    _mount_frontend(app)
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def test_root_serves_index(static_client: TestClient) -> None:
    response = static_client.get("/")
    assert response.status_code == 200
    assert "울퉁불퉁 농장 AI" in response.text


def test_exported_route_directory_is_served(static_client: TestClient) -> None:
    assert static_client.get("/map/").text == "map"


def test_unknown_route_falls_back_to_index(static_client: TestClient) -> None:
    assert "울퉁불퉁 농장 AI" in static_client.get("/no/such/page").text


def test_api_still_wins_over_the_catch_all(static_client: TestClient) -> None:
    assert static_client.get("/api/health").json() == {"status": "ok"}


def test_unknown_api_path_is_404_not_index(static_client: TestClient) -> None:
    assert static_client.get("/api/nope").status_code == 404
