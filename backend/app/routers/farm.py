"""농가 대시보드 (SPEC 4.2) 와 출하 등록 (SPEC 7.1).

HTTP 계층만 둔다 — 조회와 쓰기는 ``app/services/farm.py`` 에 있다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.farm import FarmOut, ShipmentIn, ShipmentOut
from app.services import farm as service

router = APIRouter(prefix="/api", tags=["farm"])


@router.get("/farms", response_model=list[FarmOut])
def list_farms(session: Session = Depends(get_session)) -> list[FarmOut]:
    """농가 목록 — 각 농가의 재배 작물과 예상 수확량을 함께 준다."""
    return [FarmOut.from_domain(f) for f in service.list_farms(session)]


@router.get("/farms/{farm_id}", response_model=FarmOut)
def get_farm(farm_id: int, session: Session = Depends(get_session)) -> FarmOut:
    try:
        return FarmOut.from_domain(service.get_farm(session, farm_id))
    except service.FarmError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/shipments", response_model=list[ShipmentOut])
def list_shipments(
    farm_id: int | None = Query(default=None),
    crop_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[ShipmentOut]:
    """출하 이력 — 각 출하에 붙은 거래(SPEC 7.1)까지 함께 준다."""
    try:
        lines = service.list_shipments(session, farm_id=farm_id, crop_id=crop_id)
    except service.FarmError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [ShipmentOut.from_domain(line) for line in lines]


@router.post(
    "/farms/{farm_id}/shipments",
    response_model=ShipmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_shipment(
    farm_id: int, payload: ShipmentIn, session: Session = Depends(get_session)
) -> ShipmentOut:
    """작물 등록 (SPEC 4.2 빠른 기능) — 이 출하가 도매처 추천의 입력이 된다."""
    try:
        line = service.create_shipment(
            session,
            farm_id=farm_id,
            crop_id=payload.crop_id,
            qty_kg=payload.qty_kg,
            ship_date=payload.ship_date,
            grade=payload.grade,
        )
    except service.FarmError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ShipmentOut.from_domain(line)
