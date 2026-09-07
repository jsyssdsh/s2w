"""Seed integrity — row counts plus the SPEC section 5 fixtures.

Downstream feature beads compute against these numbers, so a regression here
breaks every recommendation engine at once.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Buyer,
    BuyerType,
    ColdStorageAccess,
    ControlEvent,
    Crop,
    CropThreshold,
    Deal,
    Demand,
    Farm,
    Grade,
    Inventory,
    MarketPrice,
    Parcel,
    Region,
    SensorReading,
    Shipment,
    Smartfarm,
    User,
    WeatherDaily,
    Wholesaler,
)
from app.seed import (
    ANCHOR_DATE,
    HISTORY_DAYS,
    ONION_DEMAND_KG,
    ONION_INVENTORY_KG,
    ONION_SHIPMENTS_KG,
    seed_all,
    seed_if_empty,
)
from app.services.geo import haversine_km

ALL_TABLES = [
    User,
    Region,
    Crop,
    Parcel,
    Farm,
    Smartfarm,
    CropThreshold,
    SensorReading,
    ControlEvent,
    MarketPrice,
    WeatherDaily,
    Wholesaler,
    Buyer,
    Shipment,
    Inventory,
    Demand,
    Deal,
]


@pytest.mark.parametrize("model", ALL_TABLES, ids=lambda m: m.__tablename__)
def test_every_table_has_rows(session: Session, model: type) -> None:
    assert session.scalar(select(func.count()).select_from(model)) > 0


def test_reference_rows(session: Session) -> None:
    assert session.scalar(select(func.count()).select_from(Region)) == 6
    names = set(session.scalars(select(Crop.name)))
    assert names == {"토마토", "양파", "딸기", "오이", "배추"}


def test_seed_is_idempotent(session: Session) -> None:
    before = session.scalar(select(func.count()).select_from(MarketPrice))
    assert seed_if_empty(session) is False
    assert session.scalar(select(func.count()).select_from(MarketPrice)) == before


def test_price_history_is_24_months_per_crop(session: Session) -> None:
    for crop_id in session.scalars(select(Crop.id)):
        count = session.scalar(
            select(func.count()).select_from(MarketPrice).where(MarketPrice.crop_id == crop_id)
        )
        assert count == HISTORY_DAYS


def test_weather_matches_price_history_window(session: Session) -> None:
    for region_id in session.scalars(select(Region.id)):
        count = session.scalar(
            select(func.count()).select_from(WeatherDaily).where(WeatherDaily.region_id == region_id)
        )
        assert count == HISTORY_DAYS
    assert session.scalar(select(func.max(WeatherDaily.date))) == ANCHOR_DATE


def test_spec_5_1_tomato_anchor_price(session: Session) -> None:
    """SPEC 5.1: 기준일 토마토 예상 도매가격 2,450원/kg."""
    price = session.scalar(
        select(MarketPrice.price_per_kg)
        .join(Crop)
        .where(Crop.name == "토마토", MarketPrice.date == ANCHOR_DATE)
    )
    assert price == 2450


def test_spec_5_2_wholesaler_economics(session: Session) -> None:
    """SPEC 5.2: A/B/C 의 단가·구매량·운송비가 표와 일치한다."""
    expected = {
        "A 청과도매": (2550, 1000, 180_000),
        "B 농산물유통": (2580, 1000, 80_000),
        "C 도매시장": (2700, 800, 210_000),
    }
    home = session.scalar(select(Region).where(Region.name == "충남 논산시"))
    for name, (unit_price, capacity, transport) in expected.items():
        w = session.scalar(select(Wholesaler).where(Wholesaler.name == name))
        assert (w.unit_price_krw, w.capacity_kg) == (unit_price, capacity)
        distance = haversine_km(home.lat, home.lon, w.lat, w.lon)
        assert round(distance * w.transport_cost_per_km) == pytest.approx(transport, abs=100)


def test_spec_5_2_ranking_is_b_then_a_then_c(session: Session) -> None:
    """순수익 = 판매금액 × (1 − 수수료) − 운송비 → B 1위, A 2위, C 3위."""
    home = session.scalar(select(Region).where(Region.name == "충남 논산시"))
    offered = 1000

    def net_profit(w: Wholesaler) -> float:
        qty = min(offered, w.capacity_kg)
        gross = w.unit_price_krw * qty
        distance = haversine_km(home.lat, home.lon, w.lat, w.lon)
        return gross * (1 - w.fee_rate) - distance * w.transport_cost_per_km

    ranked = sorted(session.scalars(select(Wholesaler)), key=net_profit, reverse=True)
    assert [w.name for w in ranked] == ["B 농산물유통", "A 청과도매", "C 도매시장"]


def test_spec_5_3_tomato_inventory_split(session: Session) -> None:
    """SPEC 5.3: 토마토 1,700kg = 특상품 300 + 상품 700 + 규격외 500 + 임박 200."""
    rows = list(
        session.scalars(
            select(Inventory).join(Crop).where(Crop.name == "토마토")
        )
    )
    assert sum(r.qty_kg for r in rows) == 1700
    by_grade = {r.grade: r.qty_kg for r in rows}
    assert by_grade == {
        Grade.SPECIAL: 300,
        Grade.STANDARD: 700,
        Grade.OFFGRADE: 500,
        Grade.NEAR_EXPIRY: 200,
    }


def test_spec_5_3_all_buyer_types_present(session: Session) -> None:
    assert set(session.scalars(select(Buyer.type))) == set(BuyerType)


def test_spec_5_4_onion_oversupply(session: Session) -> None:
    """SPEC 5.4: 출하 120톤 + 재고 8톤 = 128톤 공급, 수요 100톤, 초과 28톤."""
    onion = session.scalar(select(Crop).where(Crop.name == "양파"))
    shipped = session.scalar(
        select(func.sum(Shipment.qty_kg)).where(
            Shipment.crop_id == onion.id, Shipment.ship_date >= ANCHOR_DATE
        )
    )
    stock = session.scalar(
        select(func.sum(Inventory.qty_kg)).where(Inventory.crop_id == onion.id)
    )
    demand = session.scalar(
        select(func.sum(Demand.qty_kg)).where(Demand.crop_id == onion.id)
    )
    assert shipped == ONION_SHIPMENTS_KG
    assert stock == ONION_INVENTORY_KG
    assert demand == ONION_DEMAND_KG
    assert shipped + stock - demand == 28_000


def test_spec_5_5_tomato_thresholds(session: Session) -> None:
    """SPEC 5.5: 온도 22~27℃, 습도 60~75%, 토양수분 35~55%."""
    t = session.scalar(select(CropThreshold).join(Crop).where(Crop.name == "토마토"))
    assert (t.temp_min, t.temp_max) == (22.0, 27.0)
    assert (t.humidity_min, t.humidity_max) == (60.0, 75.0)
    assert (t.soil_moisture_min, t.soil_moisture_max) == (35.0, 55.0)
    assert t.lux_min > 0


def test_spec_5_5_latest_reading_matches_worked_example(session: Session) -> None:
    """최신 토마토 센서값이 SPEC 5.5 '현재 상태' 열과 같다."""
    house = session.scalar(select(Smartfarm).join(Crop).where(Crop.name == "토마토"))
    latest = session.scalar(
        select(SensorReading)
        .where(SensorReading.smartfarm_id == house.id)
        .order_by(SensorReading.ts.desc())
        .limit(1)
    )
    threshold = session.scalar(
        select(CropThreshold).where(CropThreshold.crop_id == house.crop_id)
    )
    assert latest.temp_c == 29.4
    assert latest.humidity_pct == 68.0
    assert latest.soil_moisture_pct == 28.0
    assert latest.lux == pytest.approx(threshold.lux_min * 0.82, rel=0.01)


def test_smartfarms_have_seven_days_of_hourly_readings(session: Session) -> None:
    houses = list(session.scalars(select(Smartfarm)))
    assert len(houses) == 2
    for house in houses:
        count = session.scalar(
            select(func.count())
            .select_from(SensorReading)
            .where(SensorReading.smartfarm_id == house.id)
        )
        assert count == 7 * 24


def test_spec_5_6_parcel_fixtures(session: Session) -> None:
    """SPEC 5.6: A/B/C 농지의 면적·임대료·용수·냉장창고·도매처 거리."""
    expected = {
        "A 농지": (900, 650_000, True, ColdStorageAccess.POSSIBLE, 24.0),
        "B 농지": (1000, 550_000, True, ColdStorageAccess.LIMITED, 38.0),
        "C 농지": (750, 700_000, False, ColdStorageAccess.POSSIBLE, 17.0),
    }
    wholesalers = list(session.scalars(select(Wholesaler)))
    for name, (area, rent, water, cold, distance_km) in expected.items():
        p = session.scalar(select(Parcel).where(Parcel.name == name))
        assert (p.area_pyeong, p.monthly_rent_krw, p.water_access, p.cold_storage_access) == (
            area,
            rent,
            water,
            cold,
        )
        nearest = min(haversine_km(p.lat, p.lon, w.lat, w.lon) for w in wholesalers)
        assert nearest == pytest.approx(distance_km, abs=0.5)


def test_deals_carry_the_feedback_loop(session: Session) -> None:
    """SPEC 7.1: 실제 거래 결과가 남아 있어야 추천을 재학습할 수 있다."""
    deals = list(session.scalars(select(Deal)))
    assert any(d.status == "settled" for d in deals)
    assert all(d.agreed_price_krw > 0 for d in deals)


def test_seed_is_deterministic(tmp_path) -> None:
    """같은 시드로 두 번 생성하면 동일한 가격 시계열이 나온다."""
    from sqlalchemy.orm import sessionmaker

    from app.db import build_engine, create_all

    series: list[list[int]] = []
    for name in ("a.db", "b.db"):
        engine = build_engine(str(tmp_path / name))
        create_all(engine)
        with sessionmaker(bind=engine)() as s:
            seed_all(s)
            series.append(
                list(
                    s.scalars(
                        select(MarketPrice.price_per_kg)
                        .join(Crop)
                        .where(Crop.name == "토마토")
                        .order_by(MarketPrice.date)
                    )
                )
            )
    assert series[0] == series[1]
