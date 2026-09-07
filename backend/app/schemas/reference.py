"""Pydantic v2 schemas for the shared reference data."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lat: float
    lon: float


class CropOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    unit: str


class WholesalerOut(BaseModel):
    """도매처 (SPEC 5.2). 순수익 계산에 쓰이는 조건을 그대로 노출한다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    region_id: int
    lat: float
    lon: float
    unit_price_krw: int
    capacity_kg: int
    fee_rate: float
    transport_cost_per_km: int
