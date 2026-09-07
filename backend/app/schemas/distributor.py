"""유통업체 대시보드 API 스키마 (SPEC 4.3)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models import DealStatus, Grade


class WholesalerOut(BaseModel):
    """대시보드가 고를 수 있는 도매처."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    region_id: int
    region_name: str
    unit_price_krw: int
    capacity_kg: int
    fee_rate: float
    transport_cost_per_km: int
    inventory_lot_count: int


class FarmRecommendationOut(BaseModel):
    """AI 추천 농가 리스트 한 줄 (SPEC 4.3)."""

    model_config = ConfigDict(from_attributes=True)

    shipment_id: int
    farm_id: int
    farm_name: str
    region_id: int
    region_name: str
    crop_id: int
    crop_name: str
    grade: Grade
    grade_label: str
    ship_date: date
    qty_kg: int
    purchasable_kg: int
    unsold_kg: int
    distance_km: float
    transport_cost_krw: int
    market_price_per_kg: int
    graded_price_per_kg: int
    recommended_price_per_kg: int
    offer_pct: float
    purchase_cost_krw: int
    resale_revenue_krw: int
    fee_krw: int
    expected_net_profit_krw: int
    margin_pct: float
    price_source: str
    requested: bool
    recommended: bool
    reason: str


class RecommendationSummaryOut(BaseModel):
    """SPEC 4.3 요약 타일 — 공급 가능 건수 / AI 추천 건수 / 예상 금액."""

    model_config = ConfigDict(from_attributes=True)

    supply_count: int
    recommended_count: int
    expected_amount_krw: int
    expected_net_profit_krw: int
    supply_qty_kg: int
    purchasable_qty_kg: int
    requested_count: int


class FarmRecommendationResponse(BaseModel):
    wholesaler: WholesalerOut
    as_of: date
    window_end: date
    summary: RecommendationSummaryOut
    rows: list[FarmRecommendationOut]


class DealRequestIn(BaseModel):
    """"거래 요청 보내기" 본문."""

    wholesaler_id: int
    shipment_id: int
    #: 생략하면 추천 리스트의 권장 거래가를 쓴다.
    unit_price_krw: int | None = Field(default=None, ge=1)
    as_of: date | None = None


class DealRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    wholesaler_id: int
    wholesaler_name: str
    farm_name: str
    crop_name: str
    qty_kg: int
    unit_price_krw: int
    agreed_price_krw: int
    status: DealStatus
    created: bool
    message: str


class MarketPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    price_per_kg: int
    volume_kg: int


class MarketRowOut(BaseModel):
    """품목 한 개의 가격·수요 등락률."""

    model_config = ConfigDict(from_attributes=True)

    crop_id: int
    crop_name: str
    unit: str
    price_per_kg: int
    previous_price_per_kg: int
    price_change_pct: float
    volume_kg: int
    previous_volume_kg: int
    demand_change_pct: float
    trend: str
    series: list[MarketPointOut]


class MarketSnapshotOut(BaseModel):
    region_id: int
    region_name: str
    as_of: date
    lookback_days: int
    rows: list[MarketRowOut]


__all__ = [
    "DealRequestIn",
    "DealRequestOut",
    "FarmRecommendationOut",
    "FarmRecommendationResponse",
    "MarketPointOut",
    "MarketRowOut",
    "MarketSnapshotOut",
    "RecommendationSummaryOut",
    "WholesalerOut",
]