"""Domain data model — SQLAlchemy 2.0 declarative.

Table and column names here are the shared contract for every FarmFlow AI
feature. Downstream beads add columns and relationships, but must not rename
or repurpose what is already here.

Conventions (docs/ARCHITECTURE.md):
  * money is integer KRW, weight is kg, area is 평 (pyeong)
  * enum-ish columns are VARCHAR + CHECK, so they port to PostgreSQL unchanged
  * geography is plain lat/lon floats; distance goes through
    ``app.services.geo.haversine_km`` — the PostGIS stand-in
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """VARCHAR + CHECK constraint rather than a native DB enum type."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=lambda e: [member.value for member in e],
        validate_strings=True,
    )


# --------------------------------------------------------------------------
# Enumerations — import these instead of hand-writing the string literals.
# --------------------------------------------------------------------------


class UserRole(StrEnum):
    FARMER = "farmer"
    WHOLESALER = "wholesaler"
    BUYER = "buyer"
    LANDOWNER = "landowner"


class ColdStorageAccess(StrEnum):
    """SPEC 5.6 냉장창고 접근성."""

    POSSIBLE = "possible"       # 가능
    LIMITED = "limited"         # 제한적
    NONE = "none"               # 미확보


class ParcelStatus(StrEnum):
    """SPEC 4.4 유휴토지 지도 상태."""

    IDLE = "idle"               # 유휴
    OPERATING = "operating"     # 운영 중
    CONVERTED = "converted"     # 전환 완료


class ParcelCondition(StrEnum):
    """SPEC 4.4 지도 색상 구분."""

    BEST = "best"                           # 상태 최상 (녹)
    GOOD = "good"                           # 상태 양호 (황)
    NEEDS_IMPROVEMENT = "needs_improvement"  # 개선 필요 (적)


class ControlDevice(StrEnum):
    """SPEC 7.2 릴레이 구동장치."""

    PUMP = "pump"     # 워터펌프
    FAN = "fan"       # 환기팬
    LIGHT = "light"   # 조명


class BuyerType(StrEnum):
    """SPEC 5.3 판매처 유형."""

    MART = "mart"                 # 대형마트
    SCHOOL_MEAL = "school_meal"   # 학교급식업체
    PROCESSOR = "processor"       # 가공업체
    RESTAURANT = "restaurant"     # 지역 음식점
    LOCALFOOD = "localfood"       # 로컬푸드 매장


class Grade(StrEnum):
    """SPEC 5.3 농산물 등급/상태."""

    SPECIAL = "special"          # 특상품
    STANDARD = "standard"        # 상품(일반 규격)
    OFFGRADE = "offgrade"        # 규격 외
    NEAR_EXPIRY = "near_expiry"  # 판매기한 임박


class DealStatus(StrEnum):
    """SPEC 7.1 거래 피드백 루프."""

    PROPOSED = "proposed"    # 추천 제시
    ACCEPTED = "accepted"    # 농가 수락
    REJECTED = "rejected"    # 농가 거절
    SETTLED = "settled"      # 정산 완료


# --------------------------------------------------------------------------
# Reference tables
# --------------------------------------------------------------------------


class Region(Base):
    """시군구 단위 지역."""

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    parcels: Mapped[list["Parcel"]] = relationship(back_populates="region")
    farms: Mapped[list["Farm"]] = relationship(back_populates="region")


class Crop(Base):
    """품목 (토마토, 양파, 딸기, ...)."""

    __tablename__ = "crops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="kg")

    threshold: Mapped["CropThreshold | None"] = relationship(
        back_populates="crop", uselist=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))


class CropThreshold(Base):
    """작물별 적정 생육 기준 (SPEC 5.5)."""

    __tablename__ = "crop_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crop_id: Mapped[int] = mapped_column(
        ForeignKey("crops.id"), nullable=False, unique=True
    )
    temp_min: Mapped[float] = mapped_column(Float, nullable=False)
    temp_max: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_min: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_max: Mapped[float] = mapped_column(Float, nullable=False)
    soil_moisture_min: Mapped[float] = mapped_column(Float, nullable=False)
    soil_moisture_max: Mapped[float] = mapped_column(Float, nullable=False)
    lux_min: Mapped[float] = mapped_column(Float, nullable=False)

    crop: Mapped[Crop] = relationship(back_populates="threshold")


# --------------------------------------------------------------------------
# Land, farms and smartfarms
# --------------------------------------------------------------------------


class Parcel(Base):
    """유휴/휴경농지 (SPEC 5.6, 7.3)."""

    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    area_pyeong: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_rent_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    water_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cold_storage_access: Mapped[ColdStorageAccess] = mapped_column(
        _enum(ColdStorageAccess, "cold_storage_access"), nullable=False
    )
    soil_grade: Mapped[str] = mapped_column(String(8), nullable=False, default="B")
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[ParcelStatus] = mapped_column(
        _enum(ParcelStatus, "parcel_status"), nullable=False, default=ParcelStatus.IDLE
    )
    condition: Mapped[ParcelCondition] = mapped_column(
        _enum(ParcelCondition, "parcel_condition"),
        nullable=False,
        default=ParcelCondition.GOOD,
    )

    region: Mapped[Region] = relationship(back_populates="parcels")


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    parcel_id: Mapped[int | None] = mapped_column(ForeignKey("parcels.id"))

    region: Mapped[Region] = relationship(back_populates="farms")
    parcel: Mapped[Parcel | None] = relationship()
    smartfarms: Mapped[list["Smartfarm"]] = relationship(back_populates="farm")


class Smartfarm(Base):
    __tablename__ = "smartfarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    parcel_id: Mapped[int | None] = mapped_column(ForeignKey("parcels.id"))
    # 스마트팜 유형: 비닐하우스 / 유리온실 / 노지 등
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="비닐하우스")
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), nullable=False)
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    expected_yield_kg: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    farm: Mapped[Farm] = relationship(back_populates="smartfarms")
    crop: Mapped[Crop] = relationship()
    readings: Mapped[list["SensorReading"]] = relationship(back_populates="smartfarm")


class SensorReading(Base):
    """ESP32 → MQTT → 서버로 들어오는 센서 측정값 (SPEC 7.2)."""

    __tablename__ = "sensor_readings"
    __table_args__ = (Index("ix_sensor_readings_smartfarm_ts", "smartfarm_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    smartfarm_id: Mapped[int] = mapped_column(
        ForeignKey("smartfarms.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    temp_c: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False)
    lux: Mapped[float] = mapped_column(Float, nullable=False)
    soil_moisture_pct: Mapped[float] = mapped_column(Float, nullable=False)

    smartfarm: Mapped[Smartfarm] = relationship(back_populates="readings")


class ControlEvent(Base):
    """자동제어 실행 기록 (SPEC 5.5 자동제어 결과 열)."""

    __tablename__ = "control_events"
    __table_args__ = (Index("ix_control_events_smartfarm_ts", "smartfarm_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    smartfarm_id: Mapped[int] = mapped_column(
        ForeignKey("smartfarms.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    device: Mapped[ControlDevice] = mapped_column(
        _enum(ControlDevice, "control_device"), nullable=False
    )
    # "on" / "off" — free-form so devices can add modes later.
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # Korean explanation surfaced in the dashboard.
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Which sensor_readings column drove this command ("temp_c", "lux", ...).
    # The 환기팬 answers to both temperature and humidity, so the device alone
    # does not say what value_before/value_after are measuring.
    metric: Mapped[str | None] = mapped_column(String(32))
    value_before: Mapped[float | None] = mapped_column(Float)
    value_after: Mapped[float | None] = mapped_column(Float)


# --------------------------------------------------------------------------
# Market and weather series
# --------------------------------------------------------------------------


class MarketPrice(Base):
    """일별 도매 시세 (SPEC 5.1 학습 데이터)."""

    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("crop_id", "region_id", "date", name="uq_market_price_key"),
        Index("ix_market_prices_crop_date", "crop_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    price_per_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    volume_kg: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WeatherDaily(Base):
    """기상청 단기예보 스탠드인 (SPEC 6.2)."""

    __tablename__ = "weather_daily"
    __table_args__ = (
        UniqueConstraint("region_id", "date", name="uq_weather_daily_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    temp_avg: Mapped[float] = mapped_column(Float, nullable=False)
    rain_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sunshine_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


# --------------------------------------------------------------------------
# Distribution chain
# --------------------------------------------------------------------------


class Wholesaler(Base):
    """도매처 (SPEC 5.2)."""

    __tablename__ = "wholesalers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    # 수수료율, 0.0–1.0.
    fee_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transport_cost_per_km: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    region: Mapped[Region] = relationship()


class Buyer(Base):
    """최종 판매처 (SPEC 5.3)."""

    __tablename__ = "buyers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[BuyerType] = mapped_column(_enum(BuyerType, "buyer_type"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    demand_kg: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grade_pref: Mapped[Grade] = mapped_column(
        _enum(Grade, "grade_pref"), nullable=False, default=Grade.STANDARD
    )

    region: Mapped[Region] = relationship()


class Shipment(Base):
    """농가 출하 (SPEC 7.1 진입점)."""

    __tablename__ = "shipments"
    __table_args__ = (Index("ix_shipments_crop_date", "crop_id", "ship_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), nullable=False)
    qty_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    grade: Mapped[Grade] = mapped_column(
        _enum(Grade, "shipment_grade"), nullable=False, default=Grade.STANDARD
    )

    farm: Mapped[Farm] = relationship()
    crop: Mapped[Crop] = relationship()
    deals: Mapped[list["Deal"]] = relationship(back_populates="shipment")


class Inventory(Base):
    """도매처 재고 (SPEC 5.3, 5.4)."""

    __tablename__ = "inventory"
    __table_args__ = (Index("ix_inventory_wholesaler_crop", "wholesaler_id", "crop_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wholesaler_id: Mapped[int] = mapped_column(
        ForeignKey("wholesalers.id"), nullable=False
    )
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), nullable=False)
    qty_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[Grade] = mapped_column(
        _enum(Grade, "inventory_grade"), nullable=False, default=Grade.STANDARD
    )
    expiry_date: Mapped[date | None] = mapped_column(Date)

    wholesaler: Mapped[Wholesaler] = relationship()
    crop: Mapped[Crop] = relationship()


class Demand(Base):
    """판매처 구매 수요 (SPEC 5.4 수급 비교의 수요 쪽)."""

    __tablename__ = "demands"
    __table_args__ = (Index("ix_demands_crop_period", "crop_id", "period_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), nullable=False)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), nullable=False)
    qty_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    buyer: Mapped[Buyer] = relationship()
    crop: Mapped[Crop] = relationship()


class Deal(Base):
    """실제 거래 결과 — 추천을 다시 학습시키는 피드백 루프 (SPEC 6/7.1).

    추천 beads가 ``proposed`` 로 행을 쓰고, 농가 선택이 ``accepted`` /
    ``rejected`` 로 갱신한다.
    """

    __tablename__ = "deals"
    __table_args__ = (Index("ix_deals_shipment", "shipment_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False)
    wholesaler_id: Mapped[int] = mapped_column(
        ForeignKey("wholesalers.id"), nullable=False
    )
    agreed_price_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DealStatus] = mapped_column(
        _enum(DealStatus, "deal_status"), nullable=False, default=DealStatus.PROPOSED
    )
    decided_on: Mapped[date | None] = mapped_column(Date)

    shipment: Mapped[Shipment] = relationship(back_populates="deals")
    wholesaler: Mapped[Wholesaler] = relationship()


# --------------------------------------------------------------------------
# 유휴농지 매칭 신청 (SPEC 5.6 / 7.3)
# --------------------------------------------------------------------------


class ParcelApplicationStatus(StrEnum):
    """SPEC 7.3 매칭 신청 상태."""

    PENDING = "pending"      # 신청 접수 (협의·계약 진행 전)
    ACCEPTED = "accepted"    # 소유자 수락
    REJECTED = "rejected"    # 소유자 거절


class ParcelApplication(Base):
    """농가가 유휴농지에 낸 임대(매칭) 신청 — SPEC 7.3 "매칭 신청".

    신청이 접수되면 필지는 ``idle`` → ``operating`` 으로 넘어간다. SPEC 4.4 의
    "오늘 신청량" 지표는 ``applied_on`` 을 센다.
    """

    __tablename__ = "parcel_applications"
    __table_args__ = (
        Index("ix_parcel_applications_parcel", "parcel_id"),
        Index("ix_parcel_applications_applied_on", "applied_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), nullable=False)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), nullable=False)
    applicant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    applicant_name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    lease_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    message: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 신청 시점의 적합도 점수 (0.0–1.0). 추천 없이 직접 신청하면 비어 있다.
    match_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ParcelApplicationStatus] = mapped_column(
        _enum(ParcelApplicationStatus, "parcel_application_status"),
        nullable=False,
        default=ParcelApplicationStatus.PENDING,
    )
    applied_on: Mapped[date] = mapped_column(Date, nullable=False)

    parcel: Mapped[Parcel] = relationship()
    crop: Mapped[Crop] = relationship()
