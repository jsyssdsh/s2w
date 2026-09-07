"""SPEC 5.3 — 도매처 맞춤 판매처 연계."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Buyer, BuyerType, Crop, Grade, Wholesaler
from app.seed import ANCHOR_DATE
from app.services import buyer_match as service

# SPEC 5.3 활용 예시: 토마토 1,700kg 을 등급별로 나눈 재고와 그 판매처.
EXPECTED_MATCHES: dict[Grade, tuple[BuyerType, int]] = {
    Grade.SPECIAL: (BuyerType.MART, 300),
    Grade.STANDARD: (BuyerType.SCHOOL_MEAL, 700),
    Grade.OFFGRADE: (BuyerType.PROCESSOR, 500),
    Grade.NEAR_EXPIRY: (BuyerType.RESTAURANT, 200),
}


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


@pytest.fixture
def hub(session: Session) -> Wholesaler:
    """SPEC 5.3 재고를 들고 있는 도매처 (시드의 B 농산물유통)."""
    return session.scalars(
        select(Wholesaler).where(Wholesaler.name == "B 농산물유통")
    ).one()


@pytest.fixture
def tomato(session: Session) -> Crop:
    return session.scalars(select(Crop).where(Crop.name == "토마토")).one()


@pytest.fixture
def scratch_session(session: Session, tmp_path: Path) -> Iterator[Session]:
    """시드 DB 파일을 복사한 일회용 세션 — 여기서의 변경은 다른 테스트에 새지 않는다."""
    from app.db import build_engine

    source = session.get_bind().url.database
    assert source is not None
    scratch = tmp_path / "scratch.db"
    shutil.copy(source, scratch)
    with sessionmaker(bind=build_engine(str(scratch)), expire_on_commit=False)() as s:
        yield s


# --- 재고 조회 -------------------------------------------------------------


def test_inventory_lots_reproduce_the_1700kg_split(
    session: Session, hub: Wholesaler, tomato: Crop
) -> None:
    lots = service.list_inventory(session, hub.id, crop_id=tomato.id)

    assert sum(lot.qty_kg for lot in lots) == 1700
    assert {lot.grade: lot.qty_kg for lot in lots} == {
        Grade.SPECIAL: 300,
        Grade.STANDARD: 700,
        Grade.OFFGRADE: 500,
        Grade.NEAR_EXPIRY: 200,
    }
    # 판매기한이 짧은 로트가 먼저 온다.
    days = [lot.days_remaining for lot in lots]
    assert days == sorted(days)
    assert all(lot.expiry_date is not None for lot in lots)


def test_near_expiry_lot_is_flagged_and_urgent(
    session: Session, hub: Wholesaler, tomato: Crop
) -> None:
    lots = service.list_inventory(session, hub.id, crop_id=tomato.id)
    urgent = [lot for lot in lots if lot.is_near_expiry]

    assert [lot.grade for lot in urgent] == [Grade.NEAR_EXPIRY]
    assert urgent[0].days_remaining is not None
    assert urgent[0].days_remaining <= service.NEAR_EXPIRY_DAYS
    assert urgent[0].urgency > lots[-1].urgency


def test_inventory_endpoint(client: TestClient, hub: Wholesaler, tomato: Crop) -> None:
    response = client.get(
        f"/api/wholesalers/{hub.id}/inventory", params={"crop_id": tomato.id}
    )
    assert response.status_code == 200
    body = response.json()

    assert sum(lot["qty_kg"] for lot in body) == 1700
    assert {lot["grade"] for lot in body} == {g.value for g in Grade}
    assert all(lot["crop_name"] == "토마토" for lot in body)
    assert all(lot["days_remaining"] is not None for lot in body)
    assert [lot["near_expiry"] for lot in body].count(True) == 1
    labels = {lot["grade"]: lot["grade_label"] for lot in body}
    assert labels["special"] == "특상품"


def test_inventory_endpoint_unknown_wholesaler_is_404(client: TestClient) -> None:
    assert client.get("/api/wholesalers/99999/inventory").status_code == 404


# --- 매칭 -----------------------------------------------------------------


def test_spec_scenario_matches_four_buyer_types(
    session: Session, hub: Wholesaler, tomato: Crop
) -> None:
    """SPEC 5.3 표 그대로: 300/700/500/200 → 마트/급식/가공/음식점."""
    result = service.match_buyers(session, hub, tomato)

    assert result.total_qty_kg == 1700
    assert result.total_allocated_kg == 1700

    by_grade = {item.lot.grade: item for item in result.lots}
    assert set(by_grade) == set(EXPECTED_MATCHES)

    for grade, (buyer_type, qty) in EXPECTED_MATCHES.items():
        item = by_grade[grade]
        assert item.lot.qty_kg == qty
        assert len(item.matches) == 1, f"{grade} 로트가 여러 판매처로 쪼개졌다"
        match = item.matches[0]
        assert match.buyer_type is buyer_type
        assert match.matched_qty_kg == qty
        assert item.unallocated_kg == 0


def test_allocation_never_exceeds_buyer_demand(
    session: Session, hub: Wholesaler, tomato: Crop
) -> None:
    result = service.match_buyers(session, hub, tomato)

    allocated: dict[int, int] = {}
    demand: dict[int, int] = {}
    for item in result.lots:
        for match in item.matches:
            allocated[match.buyer_id] = allocated.get(match.buyer_id, 0) + match.matched_qty_kg
            demand[match.buyer_id] = match.demand_kg

    assert allocated, "배정이 하나도 없다"
    for buyer_id, qty in allocated.items():
        assert qty <= demand[buyer_id], f"buyer {buyer_id} 수요 초과 배정"


def test_no_double_allocation_when_demand_is_scarce(
    scratch_session: Session, hub: Wholesaler, tomato: Crop
) -> None:
    """수요를 한 곳으로 몰아도 총 배정량이 그 수요를 넘지 않는다."""
    from app.models import Demand

    session = scratch_session
    # 이 품목의 수요를 전부 지우고 마트에만 400kg 남긴다.
    for demand in session.scalars(select(Demand).where(Demand.crop_id == tomato.id)):
        session.delete(demand)
    mart = session.scalars(select(Buyer).where(Buyer.type == BuyerType.MART)).one()
    session.add(
        Demand(
            buyer_id=mart.id,
            crop_id=tomato.id,
            qty_kg=400,
            period_start=ANCHOR_DATE,
            period_end=ANCHOR_DATE + timedelta(days=14),
        )
    )
    # 나머지 판매처는 일반 수요량 사전확률도 0 으로 만든다.
    for buyer in session.scalars(select(Buyer).where(Buyer.id != mart.id)):
        buyer.demand_kg = 0
    session.flush()

    wholesaler = session.get(Wholesaler, hub.id)
    crop = session.get(Crop, tomato.id)
    assert wholesaler is not None and crop is not None
    result = service.match_buyers(session, wholesaler, crop)

    assert result.total_qty_kg == 1700
    assert result.total_allocated_kg == 400
    mart_total = sum(
        m.matched_qty_kg
        for item in result.lots
        for m in item.matches
        if m.buyer_id == mart.id
    )
    assert mart_total == 400
    assert sum(item.unallocated_kg for item in result.lots) == 1300
    # 가장 급한 로트가 그 400kg 을 먼저 가져간다.
    assert result.lots[0].lot.grade is Grade.NEAR_EXPIRY
    assert result.lots[0].allocated_kg == 200


def test_urgency_beats_grade_priors(session: Session, hub: Wholesaler, tomato: Crop) -> None:
    """특상품이라도 판매기한이 임박하면 임박 사전확률(음식점/로컬푸드)로 간다."""
    fresh = service.InventoryLot(
        id=-1,
        wholesaler_id=hub.id,
        crop_id=tomato.id,
        crop_name="토마토",
        grade=Grade.SPECIAL,
        qty_kg=100,
        expiry_date=ANCHOR_DATE + timedelta(days=12),
        days_remaining=12,
    )
    urgent = service.InventoryLot(
        id=-2,
        wholesaler_id=hub.id,
        crop_id=tomato.id,
        crop_name="토마토",
        grade=Grade.SPECIAL,
        qty_kg=100,
        expiry_date=ANCHOR_DATE + timedelta(days=1),
        days_remaining=1,
    )

    assert fresh.effective_grade is Grade.SPECIAL
    assert urgent.effective_grade is Grade.NEAR_EXPIRY
    assert urgent.urgency > fresh.urgency
    # 긴급 로트에서는 거리 가중치가 등급 가중치보다 커진다.
    grade_w, _, distance_w = service._weights(urgent.urgency)
    assert distance_w > grade_w


def test_recommendation_endpoint_reproduces_spec(
    client: TestClient, hub: Wholesaler, tomato: Crop
) -> None:
    response = client.post(
        "/api/recommendations/buyers",
        json={
            "wholesaler_id": hub.id,
            "crop_id": tomato.id,
            "as_of": ANCHOR_DATE.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["crop_name"] == "토마토"
    assert body["total_qty_kg"] == 1700
    assert body["total_allocated_kg"] == 1700
    assert body["total_unallocated_kg"] == 0

    matched = {
        item["lot"]["grade"]: (
            item["recommendations"][0]["buyer_type"],
            item["recommendations"][0]["matched_qty_kg"],
        )
        for item in body["lots"]
    }
    assert matched == {
        grade.value: (buyer_type.value, qty)
        for grade, (buyer_type, qty) in EXPECTED_MATCHES.items()
    }

    for item in body["lots"]:
        for rec in item["recommendations"]:
            assert rec["reason"].strip()
            assert "kg" in rec["reason"]
            assert 0.0 < rec["score"] <= 1.0
            assert rec["distance_km"] >= 0.0


def test_recommendation_endpoint_defaults_to_anchor_date(
    client: TestClient, hub: Wholesaler, tomato: Crop
) -> None:
    response = client.post(
        "/api/recommendations/buyers",
        json={"wholesaler_id": hub.id, "crop_id": tomato.id},
    )
    assert response.status_code == 200
    assert response.json()["as_of"] == ANCHOR_DATE.isoformat()


def test_recommendation_endpoint_unknown_ids_are_404(
    client: TestClient, hub: Wholesaler, tomato: Crop
) -> None:
    assert (
        client.post(
            "/api/recommendations/buyers",
            json={"wholesaler_id": 99999, "crop_id": tomato.id},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/recommendations/buyers",
            json={"wholesaler_id": hub.id, "crop_id": 99999},
        ).status_code
        == 404
    )
