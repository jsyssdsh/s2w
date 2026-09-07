"""농가 대시보드 입출력 스키마 (SPEC 4.2 / 7.1)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.models import DealStatus, Grade
from app.services import farm as service

#: SPEC 7.1 거래 상태의 한국어 표기 — 화면이 자체 사전을 만들지 않게 한다.
DEAL_STATUS_LABEL: dict[str, str] = {
    DealStatus.PROPOSED: "추천 제시",
    DealStatus.ACCEPTED: "거래 수락",
    DealStatus.REJECTED: "거래 거절",
    DealStatus.SETTLED: "정산 완료",
}


class CropStatusOut(BaseModel):
    smartfarm_id: int
    smartfarm_name: str
    smartfarm_type: str
    crop_id: int
    crop_name: str
    started_on: date
    expected_yield_kg: int

    @classmethod
    def from_domain(cls, c: service.CropStatus) -> "CropStatusOut":
        return cls(**vars(c))


class FarmOut(BaseModel):
    farm_id: int
    name: str
    owner_name: str
    region_id: int
    region_name: str
    parcel_id: int | None
    crops: list[CropStatusOut]
    total_expected_yield_kg: int

    @classmethod
    def from_domain(cls, f: service.FarmSummary) -> "FarmOut":
        return cls(
            farm_id=f.farm_id,
            name=f.name,
            owner_name=f.owner_name,
            region_id=f.region_id,
            region_name=f.region_name,
            parcel_id=f.parcel_id,
            crops=[CropStatusOut.from_domain(c) for c in f.crops],
            total_expected_yield_kg=f.total_expected_yield_kg,
        )


class DealLineOut(BaseModel):
    deal_id: int
    wholesaler_id: int
    wholesaler_name: str
    agreed_price_krw: int
    status: DealStatus
    status_label: str
    decided_on: date | None

    @classmethod
    def from_domain(cls, d: service.DealLine) -> "DealLineOut":
        return cls(
            deal_id=d.deal_id,
            wholesaler_id=d.wholesaler_id,
            wholesaler_name=d.wholesaler_name,
            agreed_price_krw=d.agreed_price_krw,
            status=DealStatus(d.status),
            status_label=DEAL_STATUS_LABEL[d.status],
            decided_on=d.decided_on,
        )


class ShipmentOut(BaseModel):
    shipment_id: int
    farm_id: int
    crop_id: int
    crop_name: str
    qty_kg: int
    ship_date: date
    grade: Grade
    grade_label: str
    deals: list[DealLineOut]

    @classmethod
    def from_domain(cls, s: service.ShipmentLine) -> "ShipmentOut":
        return cls(
            shipment_id=s.shipment_id,
            farm_id=s.farm_id,
            crop_id=s.crop_id,
            crop_name=s.crop_name,
            qty_kg=s.qty_kg,
            ship_date=s.ship_date,
            grade=s.grade,
            grade_label=s.grade_label,
            deals=[DealLineOut.from_domain(d) for d in s.deals],
        )


class ShipmentIn(BaseModel):
    """작물 등록 — SPEC 4.2 의 품목 · 출하량 · 출하 예정일 · 등급."""

    crop_id: int
    qty_kg: int = Field(gt=0, description="출하량 (kg)")
    ship_date: date
    grade: Grade = Grade.STANDARD
