"""Deterministic seed data for the FarmFlow AI prototype.

Everything here is reproducible: a fixed RNG seed, a fixed ``ANCHOR_DATE``
instead of ``date.today()``, and geometry derived from explicit
bearing/distance pairs. Demos and tests therefore see identical numbers on
every run.

The fixtures deliberately reproduce the worked examples in SPEC section 5 so
the feature beads have something concrete to compute against:

  * 5.1  토마토 시세가 기준일에 2,450원/kg
  * 5.2  도매처 A/B/C 의 단가·구매량·운송비
  * 5.3  토마토 1,700kg 재고를 등급별로 나눈 판매처 연계 시나리오
  * 5.4  양파 공급 128톤 vs 수요 100톤 = 초과 28톤
  * 5.5  토마토 적정 기준과 이를 벗어난 최신 센서값
  * 5.6  A/B/C 농지의 면적·임대료·용수·냉장창고·도매처 거리

Run standalone with::

    uv run python -m app.seed
"""

from __future__ import annotations

import logging
import math
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Buyer,
    BuyerType,
    ColdStorageAccess,
    ControlDevice,
    ControlEvent,
    Crop,
    CropThreshold,
    Deal,
    DealStatus,
    Demand,
    Farm,
    Grade,
    Inventory,
    MarketPrice,
    Parcel,
    ParcelCondition,
    ParcelStatus,
    Region,
    SensorReading,
    Shipment,
    Smartfarm,
    User,
    UserRole,
    WeatherDaily,
    Wholesaler,
)

logger = logging.getLogger(__name__)

RNG_SEED = 20260808

#: SPEC 5.1 uses 8월 8일 as the "today" of the worked example. Pinning it keeps
#: the generated price history stable across runs.
ANCHOR_DATE = date(2026, 8, 8)
HISTORY_DAYS = 730  # 24 months of daily observations

EARTH_RADIUS_KM = 6371.0088


def _destination(lat: float, lon: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """Point ``distance_km`` from (lat, lon) along ``bearing_deg``.

    Used so the SPEC distances (도매처 운송비, 농지-도매처 거리) fall out of
    real haversine maths instead of being stored as magic numbers.
    """
    ang = distance_km / EARTH_RADIUS_KM
    brg = math.radians(bearing_deg)
    phi1, lam1 = math.radians(lat), math.radians(lon)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(ang) + math.cos(phi1) * math.sin(ang) * math.cos(brg)
    )
    lam2 = lam1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(phi1),
        math.cos(ang) - math.sin(phi1) * math.sin(phi2),
    )
    return round(math.degrees(phi2), 6), round(math.degrees(lam2), 6)


# --------------------------------------------------------------------------
# Static fixtures
# --------------------------------------------------------------------------

# 충남 논산시와 인접 시군구. lat/lon are the real 시·군청 locations.
REGIONS: list[tuple[str, float, float]] = [
    ("충남 논산시", 36.187153, 127.098769),
    ("충남 부여군", 36.275665, 126.909820),
    ("충남 공주시", 36.446527, 127.119020),
    ("충남 계룡시", 36.274460, 127.248630),
    ("충남 금산군", 36.108930, 127.488120),
    ("전북 익산시", 35.948320, 126.957650),
]
HOME_REGION = "충남 논산시"

# name, unit, 기준일 가격(원/kg), 계절 진폭, 성수기 day-of-year, 24개월 추세
CROPS: list[tuple[str, str, int, float, int, float]] = [
    ("토마토", "kg", 2450, 0.18, 210, 0.04),
    ("양파", "kg", 1150, 0.22, 150, -0.15),  # SPEC 5.4 공급 과잉 → 하락 추세
    ("딸기", "kg", 9800, 0.30, 30, 0.06),
    ("오이", "kg", 2100, 0.20, 240, 0.02),
    ("배추", "kg", 950, 0.35, 300, -0.03),
]

# crop -> (temp_min, temp_max, hum_min, hum_max, soil_min, soil_max, lux_min)
THRESHOLDS: dict[str, tuple[float, float, float, float, float, float, float]] = {
    # SPEC 5.5: 온도 22~27℃, 습도 60~75%, 토양수분 35~55%
    "토마토": (22.0, 27.0, 60.0, 75.0, 35.0, 55.0, 15000.0),
    "양파": (15.0, 25.0, 55.0, 70.0, 30.0, 50.0, 12000.0),
    "딸기": (18.0, 25.0, 60.0, 80.0, 40.0, 60.0, 14000.0),
    "오이": (23.0, 28.0, 70.0, 85.0, 40.0, 60.0, 16000.0),
    "배추": (15.0, 22.0, 60.0, 80.0, 35.0, 55.0, 13000.0),
}

# SPEC 5.2 도매처 비교표. bearing/distance from 논산 are chosen so that
# haversine 거리 × transport_cost_per_km reproduces the 운송비 column exactly:
#   A 60km × 3,000원 = 180,000원 · B 40km × 2,000원 =  80,000원
#   C 70km × 3,000원 = 210,000원
WHOLESALERS: list[tuple[str, int, int, float, int, float, float]] = [
    # name, unit_price_krw, capacity_kg, fee_rate, transport_cost_per_km, bearing, km
    ("A 청과도매", 2550, 1000, 0.03, 3000, 45.0, 60.0),
    ("B 농산물유통", 2580, 1000, 0.03, 2000, 315.0, 40.0),
    ("C 도매시장", 2700, 800, 0.03, 3000, 90.0, 70.0),
]

# SPEC 5.6 농지 비교표. Each parcel is positioned on the 논산 side of
# wholesaler B so its nearest-도매처 distance is the 도매처 거리 column.
PARCELS: list[tuple[str, int, int, bool, ColdStorageAccess, str, ParcelCondition, float]] = [
    # name, area_pyeong, monthly_rent_krw, water, cold storage, soil, condition, km from B
    ("A 농지", 900, 650000, True, ColdStorageAccess.POSSIBLE, "1등급", ParcelCondition.BEST, 24.0),
    ("B 농지", 1000, 550000, True, ColdStorageAccess.LIMITED, "2등급", ParcelCondition.GOOD, 38.0),
    ("C 농지", 750, 700000, False, ColdStorageAccess.POSSIBLE, "2등급", ParcelCondition.NEEDS_IMPROVEMENT, 17.0),
]

# SPEC 5.3 판매처 + SPEC 5.4 대응 방안에 등장하는 업체들.
BUYERS: list[tuple[str, BuyerType, str, int, Grade]] = [
    # name, type, region, demand_kg, grade_pref
    ("한마음 대형마트", BuyerType.MART, "충남 논산시", 300, Grade.SPECIAL),
    ("논산 학교급식지원센터", BuyerType.SCHOOL_MEAL, "충남 논산시", 700, Grade.STANDARD),
    ("금강 소스가공", BuyerType.PROCESSOR, "충남 부여군", 500, Grade.OFFGRADE),
    ("계룡 향토음식점", BuyerType.RESTAURANT, "충남 계룡시", 200, Grade.NEAR_EXPIRY),
    ("공주 로컬푸드직매장", BuyerType.LOCALFOOD, "충남 공주시", 400, Grade.STANDARD),
]

# SPEC 5.3: 토마토 1,700kg 을 등급별로 나눈 재고.
TOMATO_INVENTORY: list[tuple[Grade, int, int]] = [
    # grade, qty_kg, days until expiry
    (Grade.SPECIAL, 300, 12),
    (Grade.STANDARD, 700, 9),
    (Grade.OFFGRADE, 500, 7),
    (Grade.NEAR_EXPIRY, 200, 2),
]

# SPEC 5.4 양파 시나리오 (톤 → kg).
ONION_SHIPMENTS_KG = 120_000     # 농가 출하 예정량 120톤
ONION_INVENTORY_KG = 8_000       # 도매처 기존 재고량 8톤
ONION_DEMAND_KG = 100_000        # 판매처 구매 수요량 100톤


# --------------------------------------------------------------------------
# Generators
# --------------------------------------------------------------------------


def _price_series(
    anchor_price: int, amplitude: float, peak_doy: int, trend: float, rng: random.Random
) -> list[tuple[date, int, int]]:
    """(date, price_per_kg, volume_kg) for the 24 months ending ANCHOR_DATE.

    The seasonal/trend/noise shape is generated first, then the whole series is
    rescaled so the value on ANCHOR_DATE is exactly ``anchor_price``.
    """
    days = [ANCHOR_DATE - timedelta(days=HISTORY_DAYS - 1 - i) for i in range(HISTORY_DAYS)]
    raw: list[float] = []
    for i, day in enumerate(days):
        progress = i / (HISTORY_DAYS - 1)
        seasonal = 1 + amplitude * math.cos(
            2 * math.pi * (day.timetuple().tm_yday - peak_doy) / 365.0
        )
        raw.append(seasonal * (1 + trend * progress) * rng.gauss(1.0, 0.035))

    scale = anchor_price / raw[-1]
    series: list[tuple[date, int, int]] = []
    for day, value in zip(days, raw, strict=True):
        price = max(1, round(value * scale))
        # Volume moves opposite to price — the supply/price relationship the
        # 시세 예측 모델 (SPEC 5.1) is meant to learn.
        volume = max(100, round(12000 * (2 * anchor_price - price) / anchor_price))
        series.append((day, price, volume))
    return series


def _weather_series(
    base_temp: float, rng: random.Random
) -> list[tuple[date, float, float, float]]:
    out: list[tuple[date, float, float, float]] = []
    for i in range(HISTORY_DAYS):
        day = ANCHOR_DATE - timedelta(days=HISTORY_DAYS - 1 - i)
        doy = day.timetuple().tm_yday
        temp = base_temp + 12.5 * math.cos(2 * math.pi * (doy - 205) / 365.0) + rng.gauss(0, 2.0)
        rain = max(0.0, rng.gauss(2.5 if 150 <= doy <= 250 else 0.8, 4.0))
        sunshine = max(0.0, min(14.0, 7.0 + 3.0 * math.cos(2 * math.pi * (doy - 190) / 365.0) - rain * 0.4))
        out.append((day, round(temp, 1), round(rain, 1), round(sunshine, 1)))
    return out


def _sensor_series(
    smartfarm_id: int, limits: tuple[float, ...], rng: random.Random
) -> list[SensorReading]:
    """7 days of hourly readings, mostly inside the crop's 적정 기준."""
    temp_min, temp_max, hum_min, hum_max, soil_min, soil_max, lux_min = limits
    temp_mid = (temp_min + temp_max) / 2
    hum_mid = (hum_min + hum_max) / 2
    soil_mid = (soil_min + soil_max) / 2
    start = datetime.combine(ANCHOR_DATE - timedelta(days=6), datetime.min.time())

    readings: list[SensorReading] = []
    for hour in range(7 * 24):
        ts = start + timedelta(hours=hour)
        daylight = math.sin(math.pi * max(0.0, min(1.0, (ts.hour - 6) / 12)))
        readings.append(
            SensorReading(
                smartfarm_id=smartfarm_id,
                ts=ts,
                temp_c=round(temp_mid + 2.5 * daylight + rng.gauss(0, 0.8), 1),
                humidity_pct=round(hum_mid - 4.0 * daylight + rng.gauss(0, 2.0), 1),
                lux=round(lux_min * (0.2 + 1.15 * daylight) + rng.gauss(0, 400), 0),
                soil_moisture_pct=round(soil_mid - 3.0 * daylight + rng.gauss(0, 1.5), 1),
            )
        )
    return readings


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------


def is_empty(session: Session) -> bool:
    return session.scalar(select(Region.id).limit(1)) is None


def seed_if_empty(session: Session) -> bool:
    """Populate an empty database. Returns True when rows were inserted."""
    if not is_empty(session):
        return False
    seed_all(session)
    return True


def seed_all(session: Session) -> None:
    rng = random.Random(RNG_SEED)

    # --- regions & crops --------------------------------------------------
    regions = {name: Region(name=name, lat=lat, lon=lon) for name, lat, lon in REGIONS}
    session.add_all(regions.values())

    crops: dict[str, Crop] = {}
    for name, unit, *_ in CROPS:
        crops[name] = Crop(name=name, unit=unit)
    session.add_all(crops.values())
    session.flush()

    home = regions[HOME_REGION]

    for crop_name, limits in THRESHOLDS.items():
        session.add(
            CropThreshold(
                crop_id=crops[crop_name].id,
                temp_min=limits[0],
                temp_max=limits[1],
                humidity_min=limits[2],
                humidity_max=limits[3],
                soil_moisture_min=limits[4],
                soil_moisture_max=limits[5],
                lux_min=limits[6],
            )
        )

    # --- users ------------------------------------------------------------
    farmer = User(name="김청년", role=UserRole.FARMER, phone="010-1000-0001", region_id=home.id)
    landowner = User(name="박토지", role=UserRole.LANDOWNER, phone="010-1000-0002", region_id=home.id)
    wholesaler_user = User(name="최도매", role=UserRole.WHOLESALER, phone="010-1000-0003", region_id=home.id)
    buyer_user = User(name="정구매", role=UserRole.BUYER, phone="010-1000-0004", region_id=home.id)
    session.add_all([farmer, landowner, wholesaler_user, buyer_user])
    session.flush()

    # --- wholesalers (SPEC 5.2) ------------------------------------------
    wholesalers: dict[str, Wholesaler] = {}
    for name, unit_price, capacity, fee, per_km, bearing, km in WHOLESALERS:
        lat, lon = _destination(home.lat, home.lon, bearing, km)
        w = Wholesaler(
            name=name,
            region_id=_nearest_region_id(regions, lat, lon),
            lat=lat,
            lon=lon,
            unit_price_krw=unit_price,
            capacity_kg=capacity,
            fee_rate=fee,
            transport_cost_per_km=per_km,
        )
        wholesalers[name] = w
    session.add_all(wholesalers.values())
    session.flush()

    # --- parcels (SPEC 5.6) ----------------------------------------------
    anchor = wholesalers["B 농산물유통"]
    bearing_to_home = _bearing(anchor.lat, anchor.lon, home.lat, home.lon)
    parcels: list[Parcel] = []
    for name, area, rent, water, cold, soil, condition, km_from_anchor in PARCELS:
        lat, lon = _destination(anchor.lat, anchor.lon, bearing_to_home, km_from_anchor)
        parcels.append(
            Parcel(
                name=name,
                region_id=_nearest_region_id(regions, lat, lon),
                owner_id=landowner.id,
                area_pyeong=area,
                monthly_rent_krw=rent,
                water_access=water,
                cold_storage_access=cold,
                soil_grade=soil,
                lat=lat,
                lon=lon,
                status=ParcelStatus.IDLE,
                condition=condition,
            )
        )
    # 지도 화면(SPEC 4.4)이 세 가지 상태를 모두 보여줄 수 있도록 두 필지를 전환 상태로 둔다.
    parcels[0].status = ParcelStatus.OPERATING
    parcels[1].status = ParcelStatus.CONVERTED
    session.add_all(parcels)
    session.flush()

    # --- farms & smartfarms ----------------------------------------------
    farm = Farm(name="울퉁불퉁 청년농장", owner_id=farmer.id, region_id=home.id, parcel_id=parcels[0].id)
    onion_farm = Farm(name="논산 양파영농조합", owner_id=farmer.id, region_id=home.id, parcel_id=parcels[1].id)
    session.add_all([farm, onion_farm])
    session.flush()

    tomato_house = Smartfarm(
        name="1동 토마토 재배구역",
        farm_id=farm.id,
        parcel_id=parcels[0].id,
        type="비닐하우스",
        crop_id=crops["토마토"].id,
        started_on=ANCHOR_DATE - timedelta(days=120),
        expected_yield_kg=1000,
    )
    strawberry_house = Smartfarm(
        name="2동 딸기 재배구역",
        farm_id=farm.id,
        parcel_id=parcels[0].id,
        type="유리온실",
        crop_id=crops["딸기"].id,
        started_on=ANCHOR_DATE - timedelta(days=60),
        expected_yield_kg=400,
    )
    session.add_all([tomato_house, strawberry_house])
    session.flush()

    # --- sensor readings (SPEC 5.5) --------------------------------------
    tomato_limits = THRESHOLDS["토마토"]
    tomato_readings = _sensor_series(tomato_house.id, tomato_limits, rng)
    # 가장 최근 측정값은 SPEC 5.5 표의 "현재 상태" 열과 일치시킨다.
    latest = tomato_readings[-1]
    latest.temp_c = 29.4
    latest.humidity_pct = 68.0
    latest.soil_moisture_pct = 28.0
    latest.lux = round(tomato_limits[6] * 0.82)
    session.add_all(tomato_readings)
    session.add_all(_sensor_series(strawberry_house.id, THRESHOLDS["딸기"], rng))

    # --- control events (SPEC 5.5 자동제어 결과) --------------------------
    control_ts = datetime.combine(ANCHOR_DATE, datetime.min.time()) + timedelta(hours=14)
    session.add_all(
        [
            ControlEvent(
                smartfarm_id=tomato_house.id,
                ts=control_ts,
                device=ControlDevice.FAN,
                action="on",
                reason="온도 29.4℃ — 적정 상한 27.0℃ 초과, 환기 가동",
                value_before=29.4,
                value_after=26.5,
            ),
            ControlEvent(
                smartfarm_id=tomato_house.id,
                ts=control_ts + timedelta(minutes=5),
                device=ControlDevice.PUMP,
                action="on",
                reason="토양수분 28.0% — 적정 하한 35.0% 미만, 급수 가동",
                value_before=28.0,
                value_after=41.0,
            ),
            ControlEvent(
                smartfarm_id=tomato_house.id,
                ts=control_ts + timedelta(minutes=10),
                device=ControlDevice.LIGHT,
                action="on",
                reason="조도 기준의 82% — 보광 가동",
                value_before=float(round(tomato_limits[6] * 0.82)),
                value_after=float(round(tomato_limits[6] * 1.01)),
            ),
        ]
    )

    # --- market prices & weather -----------------------------------------
    for name, _unit, anchor_price, amplitude, peak_doy, trend in CROPS:
        for day, price, volume in _price_series(anchor_price, amplitude, peak_doy, trend, rng):
            session.add(
                MarketPrice(
                    crop_id=crops[name].id,
                    region_id=home.id,
                    date=day,
                    price_per_kg=price,
                    volume_kg=volume,
                )
            )

    for region in regions.values():
        # 남쪽일수록 평균기온이 높다 — 위도로 기준 온도를 조금 흔들어 준다.
        base_temp = 13.0 + (36.45 - region.lat) * 2.0
        for day, temp, rain, sun in _weather_series(base_temp, rng):
            session.add(
                WeatherDaily(
                    region_id=region.id,
                    date=day,
                    temp_avg=temp,
                    rain_mm=rain,
                    sunshine_hours=sun,
                )
            )

    # --- buyers -----------------------------------------------------------
    buyers: dict[BuyerType, Buyer] = {}
    for name, btype, region_name, demand, grade in BUYERS:
        region = regions[region_name]
        # 판매처는 시군청에서 조금 떨어진 곳에 둔다 (지도 화면에서 겹치지 않도록).
        lat, lon = _destination(region.lat, region.lon, rng.uniform(0, 360), rng.uniform(1.0, 6.0))
        buyer = Buyer(
            name=name,
            type=btype,
            region_id=region.id,
            lat=lat,
            lon=lon,
            demand_kg=demand,
            grade_pref=grade,
        )
        buyers[btype] = buyer
    session.add_all(buyers.values())
    session.flush()

    # --- SPEC 5.3: 토마토 1,700kg 등급별 재고 + 대응 수요 ------------------
    hub = wholesalers["B 농산물유통"]
    for grade, qty, days_left in TOMATO_INVENTORY:
        session.add(
            Inventory(
                wholesaler_id=hub.id,
                crop_id=crops["토마토"].id,
                qty_kg=qty,
                grade=grade,
                expiry_date=ANCHOR_DATE + timedelta(days=days_left),
            )
        )
    grade_to_buyer = {
        Grade.SPECIAL: BuyerType.MART,
        Grade.STANDARD: BuyerType.SCHOOL_MEAL,
        Grade.OFFGRADE: BuyerType.PROCESSOR,
        Grade.NEAR_EXPIRY: BuyerType.RESTAURANT,
    }
    for grade, qty, _days in TOMATO_INVENTORY:
        session.add(
            Demand(
                buyer_id=buyers[grade_to_buyer[grade]].id,
                crop_id=crops["토마토"].id,
                qty_kg=qty,
                period_start=ANCHOR_DATE,
                period_end=ANCHOR_DATE + timedelta(days=14),
            )
        )

    # --- SPEC 5.4: 양파 공급 128톤 vs 수요 100톤 --------------------------
    onion = crops["양파"]
    onion_ship_dates = [ANCHOR_DATE + timedelta(days=offset) for offset in (3, 7, 11, 15)]
    per_shipment = ONION_SHIPMENTS_KG // len(onion_ship_dates)
    onion_shipments: list[Shipment] = []
    for ship_date in onion_ship_dates:
        s = Shipment(
            farm_id=onion_farm.id,
            crop_id=onion.id,
            qty_kg=per_shipment,
            ship_date=ship_date,
            grade=Grade.STANDARD,
        )
        onion_shipments.append(s)
    session.add_all(onion_shipments)
    session.add(
        Inventory(
            wholesaler_id=hub.id,
            crop_id=onion.id,
            qty_kg=ONION_INVENTORY_KG,
            grade=Grade.STANDARD,
            expiry_date=ANCHOR_DATE + timedelta(days=30),
        )
    )
    # 수요 100톤을 판매처 다섯 곳에 나눠 담는다.
    onion_demand_split = [40_000, 25_000, 15_000, 10_000, 10_000]
    assert sum(onion_demand_split) == ONION_DEMAND_KG
    for buyer, qty in zip(buyers.values(), onion_demand_split, strict=True):
        session.add(
            Demand(
                buyer_id=buyer.id,
                crop_id=onion.id,
                qty_kg=qty,
                period_start=ANCHOR_DATE,
                period_end=ANCHOR_DATE + timedelta(days=21),
            )
        )

    # --- SPEC 5.2 / 7.1: 토마토 1,000kg 출하와 그 거래 피드백 --------------
    tomato_shipment = Shipment(
        farm_id=farm.id,
        crop_id=crops["토마토"].id,
        qty_kg=1000,
        ship_date=ANCHOR_DATE,
        grade=Grade.SPECIAL,
    )
    session.add(tomato_shipment)
    session.flush()

    # 지난 출하에서 농가가 실제로 선택한 거래 — 추천 모델의 학습 신호.
    previous = Shipment(
        farm_id=farm.id,
        crop_id=crops["토마토"].id,
        qty_kg=800,
        ship_date=ANCHOR_DATE - timedelta(days=21),
        grade=Grade.STANDARD,
    )
    session.add(previous)
    session.flush()
    session.add_all(
        [
            Deal(
                shipment_id=previous.id,
                wholesaler_id=hub.id,
                agreed_price_krw=2580 * 800,
                status=DealStatus.SETTLED,
                decided_on=ANCHOR_DATE - timedelta(days=20),
            ),
            Deal(
                shipment_id=tomato_shipment.id,
                wholesaler_id=hub.id,
                agreed_price_krw=2580 * 1000,
                status=DealStatus.PROPOSED,
                decided_on=None,
            ),
        ]
    )

    session.commit()


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _nearest_region_id(regions: dict[str, Region], lat: float, lon: float) -> int:
    from app.services.geo import haversine_km

    nearest = min(regions.values(), key=lambda r: haversine_km(lat, lon, r.lat, r.lon))
    return nearest.id


def main() -> None:  # pragma: no cover - CLI entry point
    logging.basicConfig(level=logging.INFO)
    from app.db import SessionLocal, create_all

    create_all()
    with SessionLocal() as session:
        if seed_if_empty(session):
            logger.info("seeded database")
        else:
            logger.info("database already populated — nothing to do")


if __name__ == "__main__":  # pragma: no cover
    main()
