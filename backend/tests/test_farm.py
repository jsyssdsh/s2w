"""농가 대시보드 API — SPEC 4.2 메인 현황과 SPEC 7.1 출하 등록."""

from __future__ import annotations

import shutil
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Grade
from app.seed import ANCHOR_DATE
from app.services import farm as service

TOMATO_FARM = "울퉁불퉁 청년농장"


@pytest.fixture(scope="module")
def seeded_db_file(tmp_path_factory: pytest.TempPathFactory):
    """시드를 한 번만 채운 SQLite 파일. 쓰기 테스트가 여기서 복사해 쓴다."""
    from app.db import build_engine, create_all
    from app.seed import seed_all

    path = tmp_path_factory.mktemp("farm-db") / "seeded.db"
    engine = build_engine(str(path))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        seed_all(session)
    engine.dispose()
    return path


@pytest.fixture
def db_factory(seeded_db_file, tmp_path):
    """테스트 하나만의 DB — 출하 등록은 커밋하므로 파일 복사로 격리한다."""
    from app.db import build_engine

    path = tmp_path / "test.db"
    shutil.copy(seeded_db_file, path)
    engine = build_engine(str(path))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def client(db_factory: sessionmaker) -> TestClient:
    from app.db import get_session
    from app.main import app

    def override() -> Session:
        with db_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _tomato_farm(client: TestClient) -> dict:
    farms = client.get("/api/farms").json()
    return next(f for f in farms if f["name"] == TOMATO_FARM)


def test_farm_list_carries_current_crops_and_expected_yield(client: TestClient) -> None:
    """SPEC 4.2 메인 현황의 "현재 작물 / 예상 수확량" 은 API 에서 온다."""
    farm = _tomato_farm(client)

    crops = {c["crop_name"]: c for c in farm["crops"]}
    assert set(crops) == {"토마토", "딸기"}
    assert crops["토마토"]["expected_yield_kg"] == 1000
    assert crops["딸기"]["expected_yield_kg"] == 400
    assert farm["total_expected_yield_kg"] == 1400
    assert farm["region_name"] == "충남 논산시"
    # 재배구역 번호 순 — 1동 토마토가 "현재 작물" 이다.
    assert farm["crops"][0]["crop_name"] == "토마토"


def test_unknown_farm_is_404(client: TestClient) -> None:
    assert client.get("/api/farms/9999").status_code == 404
    assert client.get("/api/shipments", params={"farm_id": 9999}).status_code == 404


def test_shipments_carry_the_deal_feedback_loop(client: TestClient) -> None:
    """SPEC 4.2 거래 현황 — 출하에 붙은 거래가 도매처 이름과 함께 온다."""
    farm = _tomato_farm(client)
    rows = client.get("/api/shipments", params={"farm_id": farm["farm_id"]}).json()

    assert rows, "시드가 토마토 출하를 보장한다"
    # 최근 출하 예정일이 먼저 온다.
    dates = [r["ship_date"] for r in rows]
    assert dates == sorted(dates, reverse=True)

    with_deals = [r for r in rows if r["deals"]]
    assert with_deals, "시드의 토마토 출하에는 거래 이력이 있다"
    deal = with_deals[0]["deals"][0]
    assert deal["wholesaler_name"]
    assert deal["status_label"] in {"추천 제시", "거래 수락", "거래 거절", "정산 완료"}


def test_register_crop_creates_a_shipment(client: TestClient) -> None:
    """작물 등록 (SPEC 4.2 빠른 기능) → shipments 행 하나."""
    farm = _tomato_farm(client)
    ship_date = (ANCHOR_DATE + timedelta(days=5)).isoformat()

    created = client.post(
        f"/api/farms/{farm['farm_id']}/shipments",
        json={"crop_id": 1, "qty_kg": 1000, "ship_date": ship_date, "grade": "special"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["crop_name"] == "토마토"
    assert body["qty_kg"] == 1000
    assert body["ship_date"] == ship_date
    assert body["grade_label"] == "특상품"
    assert body["deals"] == []

    listed = client.get("/api/shipments", params={"farm_id": farm["farm_id"]}).json()
    assert body["shipment_id"] in {r["shipment_id"] for r in listed}


def test_register_crop_rejects_bad_input(client: TestClient) -> None:
    farm = _tomato_farm(client)
    payload = {"crop_id": 1, "qty_kg": 0, "ship_date": ANCHOR_DATE.isoformat()}
    assert (
        client.post(f"/api/farms/{farm['farm_id']}/shipments", json=payload).status_code
        == 422
    )

    payload["qty_kg"] = 100
    payload["crop_id"] = 9999
    assert (
        client.post(f"/api/farms/{farm['farm_id']}/shipments", json=payload).status_code
        == 404
    )


def test_wholesaler_reference_matches_spec_5_2_conditions(client: TestClient) -> None:
    """도매처 이름 조회원 — SPEC 5.2 표의 A/B/C 조건이 그대로 나온다."""
    rows = {w["name"]: w for w in client.get("/api/wholesalers").json()}

    assert rows["A 청과도매"]["unit_price_krw"] == 2550
    assert rows["B 농산물유통"]["unit_price_krw"] == 2580
    assert rows["C 도매시장"]["unit_price_krw"] == 2700
    assert rows["C 도매시장"]["capacity_kg"] == 800
    assert all(w["fee_rate"] == pytest.approx(0.03) for w in rows.values())


def test_service_labels_every_grade(db_factory: sessionmaker) -> None:
    with db_factory() as session:
        for grade in Grade:
            assert service.GRADE_LABEL[grade]
