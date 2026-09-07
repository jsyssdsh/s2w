"""SPEC 7.3 유휴농지 등록 — ``POST /api/parcels``.

등록은 DB 를 바꾸므로 공유 시드 DB 가 아니라 테스트마다 새 파일을 쓴다.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Crop, Parcel, ParcelStatus, Region, User, UserRole

# 시드 농지(A/B/C)와 겨루지 않는, 일부러 조건이 나쁜 필지.
# 농업용수가 없어 SPEC 5.6 하드 페널티를 그대로 받는다.
NEW_PARCEL = {
    "name": "D 농지",
    "area_pyeong": 2000,
    "monthly_rent_krw": 1_000_000,
    "water_access": False,
    "cold_storage_access": "none",
    "soil_grade": "3등급",
    "condition": "needs_improvement",
    "owner_name": "최소유",
    "owner_phone": "010-1000-0009",
}


@pytest.fixture
def fresh(tmp_path) -> Iterator[tuple[TestClient, Session]]:
    """새 시드 DB 하나를 라우터와 테스트가 함께 쓴다."""
    from app.db import build_engine, create_all, get_session
    from app.main import app
    from app.seed import seed_all

    engine = build_engine(str(tmp_path / "register.db"))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        seed_all(session)

    def override() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    try:
        with factory() as session, TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()


def _region_id(session: Session, name: str) -> int:
    return session.scalars(select(Region).where(Region.name == name)).one().id


def _payload(session: Session, **overrides) -> dict:
    return {**NEW_PARCEL, "region_id": _region_id(session, "충남 논산시"), **overrides}


def test_registration_returns_an_idle_map_feature(fresh) -> None:
    """등록 응답은 지도(SPEC 4.4)가 쓰는 GeoJSON 피처 그대로다."""
    client, session = fresh

    response = client.post("/api/parcels", json=_payload(session))
    assert response.status_code == 201
    feature = response.json()

    assert feature["type"] == "Feature"
    props = feature["properties"]
    assert props["name"] == "D 농지"
    assert props["area_pyeong"] == 2000
    assert props["region_name"] == "충남 논산시"
    # 등록 직후는 언제나 유휴다 — 상태를 넘기는 것은 매칭 신청뿐.
    assert props["status"] == "idle"
    assert props["status_label"] == "유휴"
    # 개선 필요(적) 색상까지 응답에 실린다.
    assert props["condition_label"] == "개선 필요"
    assert props["color"] == "red"

    # 좌표를 안 줬으므로 시군구 중심이 들어간다.
    region = session.scalars(select(Region).where(Region.name == "충남 논산시")).one()
    assert feature["geometry"]["coordinates"] == [region.lon, region.lat]


def test_registered_parcel_shows_up_on_the_map_and_summary(fresh) -> None:
    client, session = fresh

    before = client.get("/api/parcels/summary").json()
    created = client.post("/api/parcels", json=_payload(session)).json()

    after = client.get("/api/parcels/summary").json()
    assert after["total_count"] == before["total_count"] + 1
    assert after["idle_count"] == before["idle_count"] + 1

    geojson = client.get("/api/parcels/geojson").json()
    ids = [f["properties"]["id"] for f in geojson["features"]]
    assert created["id"] in ids

    # SPEC 4.5 상세도 곧바로 열린다 — 소유자 연락처가 붙어 있다.
    detail = client.get(f"/api/parcels/{created['id']}").json()
    assert detail["owner"]["name"] == "최소유"
    assert detail["owner"]["phone"] == "010-1000-0009"
    assert detail["cold_storage_label"] == "미확보"


def test_registered_parcel_enters_the_match_ranking_last(fresh) -> None:
    """SPEC 7.3: 등록 → 농가 조건 입력 → 적합도 분석 → 매칭 신청."""
    client, session = fresh
    crop_id = session.scalars(select(Crop).where(Crop.name == "딸기")).one().id

    created = client.post("/api/parcels", json=_payload(session)).json()
    match = client.post(
        "/api/parcels/match",
        json={
            "crop_id": crop_id,
            "area_min_pyeong": 700,
            "area_max_pyeong": 1000,
            "budget_krw_per_month": 700_000,
        },
    ).json()

    ranked = {row["name"]: row["rank"] for row in match["results"]}
    # SPEC 5.6 순위는 그대로고, 용수 없는 새 필지가 맨 뒤에 붙는다.
    assert ranked["A 농지"] == 1
    assert ranked["B 농지"] == 2
    assert ranked["D 농지"] == len(ranked)

    row = next(r for r in match["results"] if r["parcel_id"] == created["id"])
    assert row["total_score"] < min(
        r["total_score"] for r in match["results"] if r["parcel_id"] != created["id"]
    )

    # 그래도 매칭 신청은 받는다 — 유휴 상태이기 때문이다 (SPEC 7.3).
    applied = client.post(
        f"/api/parcels/{created['id']}/applications",
        json={"crop_id": crop_id, "applicant_name": "김청년", "match_score": row["total_score"]},
    )
    assert applied.status_code == 201
    assert applied.json()["parcel_status_label"] == "운영 중"


def test_registration_creates_a_landowner_user(fresh) -> None:
    client, session = fresh

    client.post("/api/parcels", json=_payload(session))

    owner = session.scalars(select(User).where(User.name == "최소유")).one()
    assert owner.role is UserRole.LANDOWNER


def test_registration_without_an_owner_leaves_the_contact_empty(fresh) -> None:
    client, session = fresh
    payload = _payload(session, owner_name=None, owner_phone=None)

    created = client.post("/api/parcels", json=payload).json()

    assert client.get(f"/api/parcels/{created['id']}").json()["owner"] is None


def test_explicit_coordinates_are_kept(fresh) -> None:
    client, session = fresh
    payload = _payload(session, lat=36.2, lon=127.1)

    feature = client.post("/api/parcels", json=payload).json()

    assert feature["geometry"]["coordinates"] == [127.1, 36.2]


def test_duplicate_name_in_the_same_region_is_409(fresh) -> None:
    client, session = fresh

    assert client.post("/api/parcels", json=_payload(session)).status_code == 201
    clash = client.post("/api/parcels", json=_payload(session))

    assert clash.status_code == 409
    assert "D 농지" in clash.json()["detail"]


def test_same_name_in_another_region_is_allowed(fresh) -> None:
    client, session = fresh

    assert client.post("/api/parcels", json=_payload(session)).status_code == 201
    other = _payload(session, region_id=_region_id(session, "충남 부여군"))

    assert client.post("/api/parcels", json=other).status_code == 201


def test_unknown_region_is_404(fresh) -> None:
    client, session = fresh

    response = client.post("/api/parcels", json=_payload(session, region_id=9999))

    assert response.status_code == 404
    assert "detail" in response.json()


@pytest.mark.parametrize(
    "overrides",
    [
        {"area_pyeong": 0},
        {"monthly_rent_krw": -1},
        {"name": ""},
        {"cold_storage_access": "somewhere"},
        {"lat": 120.0},
    ],
    ids=["area", "rent", "name", "cold_storage", "lat"],
)
def test_invalid_input_is_422(fresh, overrides: dict) -> None:
    client, session = fresh

    assert client.post("/api/parcels", json=_payload(session, **overrides)).status_code == 422


def test_registration_never_starts_operating(fresh) -> None:
    """상태는 요청으로 정할 수 없다 — 매칭 신청만 필지를 넘긴다."""
    client, session = fresh

    created = client.post("/api/parcels", json=_payload(session, status="operating")).json()

    parcel = session.get(Parcel, created["id"])
    assert parcel is not None
    assert parcel.status is ParcelStatus.IDLE
