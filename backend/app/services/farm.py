"""농가 대시보드의 읽기/쓰기 (SPEC 4.2 / 7.1 출하 등록).

화면(SPEC 4.2)이 필요로 하는 "농가 한 곳의 지금 상태" 를 모으는 곳이다.
시세 예측(5.1) · 도매처 추천(5.2) · 스마트팜(5.5) 은 각자의 서비스가 이미
가지고 있으므로 여기서 다시 계산하지 않는다. 이 모듈이 채우는 빈칸은 두 개다.

* **현재 작물과 예상 수확량** — `smartfarms` 를 농가 단위로 묶어 준다.
* **작물 등록** — SPEC 4.2 빠른 기능의 첫 번째. `shipments` 행을 만들고,
  그 출하가 SPEC 5.2 추천과 SPEC 7.1 거래 기록의 입력이 된다.

docs/ARCHITECTURE.md 5절대로 계산값은 그대로 돌려주고 표기는 스키마에서 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Crop, Deal, Farm, Grade, Region, Shipment, User, Wholesaler

#: SPEC 5.3 의 등급 표기를 농가 화면에서도 그대로 쓴다.
GRADE_LABEL: dict[Grade, str] = {
    Grade.SPECIAL: "특상품",
    Grade.STANDARD: "상품",
    Grade.OFFGRADE: "규격 외",
    Grade.NEAR_EXPIRY: "판매기한 임박",
}


class FarmError(LookupError):
    """참조하는 행이 없을 때. 라우터가 404 로 옮긴다."""


@dataclass(frozen=True)
class CropStatus:
    """농가가 지금 기르고 있는 작물 한 줄 (SPEC 4.2 "현재 작물 / 예상 수확량")."""

    smartfarm_id: int
    smartfarm_name: str
    smartfarm_type: str
    crop_id: int
    crop_name: str
    started_on: date
    expected_yield_kg: int


@dataclass(frozen=True)
class FarmSummary:
    farm_id: int
    name: str
    owner_name: str
    region_id: int
    region_name: str
    parcel_id: int | None
    crops: list[CropStatus]
    #: 재배 중인 작물의 예상 수확량 합계 (kg)
    total_expected_yield_kg: int


def list_farms(session: Session) -> list[FarmSummary]:
    """농가 목록. 화면은 첫 번째 농가를 기본 선택으로 연다."""
    farms = list(session.scalars(select(Farm).order_by(Farm.id)))
    return [_summarise(session, farm) for farm in farms]


def get_farm(session: Session, farm_id: int) -> FarmSummary:
    farm = session.get(Farm, farm_id)
    if farm is None:
        raise FarmError(f"farm {farm_id} not found")
    return _summarise(session, farm)


def _summarise(session: Session, farm: Farm) -> FarmSummary:
    region = session.get(Region, farm.region_id)
    owner = session.get(User, farm.owner_id)
    crops = [
        CropStatus(
            smartfarm_id=house.id,
            smartfarm_name=house.name,
            smartfarm_type=house.type,
            crop_id=house.crop_id,
            crop_name=house.crop.name,
            started_on=house.started_on,
            expected_yield_kg=house.expected_yield_kg,
        )
        # 시작일이 최근인 재배구역을 앞에 둔다 — "현재 작물" 은 가장 최근 작기다.
        for house in sorted(
            farm.smartfarms, key=lambda h: (h.started_on, h.id), reverse=True
        )
    ]
    return FarmSummary(
        farm_id=farm.id,
        name=farm.name,
        owner_name=owner.name if owner else "",
        region_id=farm.region_id,
        region_name=region.name if region else "",
        parcel_id=farm.parcel_id,
        crops=crops,
        total_expected_yield_kg=sum(c.expected_yield_kg for c in crops),
    )


# --------------------------------------------------------------------------
# 출하 (작물 등록) — SPEC 4.2 빠른 기능 / SPEC 7.1 의 시작점
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DealLine:
    """출하 한 건에 붙은 거래 기록. `deals` 는 도매처 이름을 들고 있지 않다."""

    deal_id: int
    wholesaler_id: int
    wholesaler_name: str
    agreed_price_krw: int
    status: str
    decided_on: date | None


@dataclass(frozen=True)
class ShipmentLine:
    shipment_id: int
    farm_id: int
    crop_id: int
    crop_name: str
    qty_kg: int
    ship_date: date
    grade: Grade
    grade_label: str
    deals: list[DealLine]


def create_shipment(
    session: Session,
    *,
    farm_id: int,
    crop_id: int,
    qty_kg: int,
    ship_date: date,
    grade: Grade = Grade.STANDARD,
) -> ShipmentLine:
    """작물 등록 — 농가의 출하 예정을 남긴다."""
    farm = session.get(Farm, farm_id)
    if farm is None:
        raise FarmError(f"farm {farm_id} not found")
    crop = session.get(Crop, crop_id)
    if crop is None:
        raise FarmError(f"crop {crop_id} not found")

    shipment = Shipment(
        farm_id=farm_id,
        crop_id=crop_id,
        qty_kg=qty_kg,
        ship_date=ship_date,
        grade=grade,
    )
    session.add(shipment)
    session.commit()
    session.refresh(shipment)
    return _shipment_line(session, shipment, {})


def list_shipments(
    session: Session, *, farm_id: int | None = None, crop_id: int | None = None
) -> list[ShipmentLine]:
    """출하 이력. 최근 출하 예정일이 먼저 온다 (SPEC 4.2 거래 현황의 뼈대)."""
    if farm_id is not None and session.get(Farm, farm_id) is None:
        raise FarmError(f"farm {farm_id} not found")

    stmt = select(Shipment)
    if farm_id is not None:
        stmt = stmt.where(Shipment.farm_id == farm_id)
    if crop_id is not None:
        stmt = stmt.where(Shipment.crop_id == crop_id)
    shipments = list(
        session.scalars(stmt.order_by(Shipment.ship_date.desc(), Shipment.id.desc()))
    )
    names = _wholesaler_names(session)
    return [_shipment_line(session, s, names) for s in shipments]


def _wholesaler_names(session: Session) -> dict[int, str]:
    return {
        w_id: name
        for w_id, name in session.execute(select(Wholesaler.id, Wholesaler.name)).all()
    }


def _shipment_line(
    session: Session, shipment: Shipment, names: dict[int, str]
) -> ShipmentLine:
    deals = list(
        session.scalars(
            select(Deal).where(Deal.shipment_id == shipment.id).order_by(Deal.id)
        )
    )
    if deals and not names:
        names = _wholesaler_names(session)
    return ShipmentLine(
        shipment_id=shipment.id,
        farm_id=shipment.farm_id,
        crop_id=shipment.crop_id,
        crop_name=shipment.crop.name,
        qty_kg=shipment.qty_kg,
        ship_date=shipment.ship_date,
        grade=shipment.grade,
        grade_label=GRADE_LABEL[shipment.grade],
        deals=[
            DealLine(
                deal_id=d.id,
                wholesaler_id=d.wholesaler_id,
                wholesaler_name=names.get(d.wholesaler_id, ""),
                agreed_price_krw=d.agreed_price_krw,
                status=str(d.status),
                decided_on=d.decided_on,
            )
            for d in deals
        ],
    )
