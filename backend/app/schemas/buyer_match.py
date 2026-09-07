"""SPEC 5.3 도매처 맞춤 판매처 연계 — 입출력 스키마 (Pydantic v2)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models import BuyerType, Grade
from app.services.buyer_match import DEFAULT_AS_OF


class InventoryLotOut(BaseModel):
    """도매처 재고 한 줄 — 등급 · 수량 · 판매기한 · 잔여일."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    wholesaler_id: int
    crop_id: int
    crop_name: str
    grade: Grade
    grade_label: str
    qty_kg: int
    expiry_date: date | None
    days_remaining: int | None
    near_expiry: bool


class BuyerMatchOut(BaseModel):
    """로트 하나에 대한 판매처 한 곳의 추천."""

    buyer_id: int
    buyer_name: str
    buyer_type: BuyerType
    buyer_type_label: str
    distance_km: float
    demand_kg: int
    matched_qty_kg: int
    score: float
    reason: str


class LotRecommendationOut(BaseModel):
    lot: InventoryLotOut
    allocated_kg: int
    unallocated_kg: int
    recommendations: list[BuyerMatchOut]


class BuyerMatchRequest(BaseModel):
    """``POST /api/recommendations/buyers`` 요청 본문."""

    wholesaler_id: int = Field(..., ge=1)
    crop_id: int = Field(..., ge=1)
    as_of: date = DEFAULT_AS_OF


class BuyerMatchResponse(BaseModel):
    wholesaler_id: int
    wholesaler_name: str
    crop_id: int
    crop_name: str
    as_of: date
    total_qty_kg: int
    total_allocated_kg: int
    total_unallocated_kg: int
    lots: list[LotRecommendationOut]
