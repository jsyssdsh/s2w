"""SPEC 5.3 도매처 맞춤 판매처 연계 — HTTP 계층.

계산은 전부 ``app/services/buyer_match.py`` 에 있다. 여기서는 조회·검증과
표시용 반올림만 한다 (ARCHITECTURE 5절: 반올림은 표현 계층에서).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.buyer_match import (
    BuyerMatchOut,
    BuyerMatchRequest,
    BuyerMatchResponse,
    InventoryLotOut,
    LotRecommendationOut,
)
from app.services import buyer_match as service

router = APIRouter(prefix="/api", tags=["buyer-match"])

_DISTANCE_DP = 2
_SCORE_DP = 4


def _lot_out(lot: service.InventoryLot) -> InventoryLotOut:
    return InventoryLotOut(
        id=lot.id,
        wholesaler_id=lot.wholesaler_id,
        crop_id=lot.crop_id,
        crop_name=lot.crop_name,
        grade=lot.grade,
        grade_label=service.GRADE_LABEL[lot.grade],
        qty_kg=lot.qty_kg,
        expiry_date=lot.expiry_date,
        days_remaining=lot.days_remaining,
        near_expiry=lot.is_near_expiry,
    )


def _match_out(match: service.BuyerMatch) -> BuyerMatchOut:
    return BuyerMatchOut(
        buyer_id=match.buyer_id,
        buyer_name=match.buyer_name,
        buyer_type=match.buyer_type,
        buyer_type_label=service.BUYER_TYPE_LABEL[match.buyer_type],
        distance_km=round(match.distance_km, _DISTANCE_DP),
        demand_kg=match.demand_kg,
        matched_qty_kg=match.matched_qty_kg,
        score=round(match.score, _SCORE_DP),
        reason=match.reason,
    )


@router.get("/wholesalers/{wholesaler_id}/inventory", response_model=list[InventoryLotOut])
def list_inventory(
    wholesaler_id: int,
    crop_id: int | None = Query(default=None, description="품목으로 거르기"),
    as_of: date = Query(default=service.DEFAULT_AS_OF, description="기준일"),
    session: Session = Depends(get_session),
) -> list[InventoryLotOut]:
    """도매처 재고 — 등급, 수량, 판매기한, 기준일 대비 잔여일."""
    if service.get_wholesaler(session, wholesaler_id) is None:
        raise HTTPException(status_code=404, detail="도매처를 찾을 수 없습니다")
    lots = service.list_inventory(
        session, wholesaler_id, crop_id=crop_id, as_of=as_of
    )
    return [_lot_out(lot) for lot in lots]


@router.post("/recommendations/buyers", response_model=BuyerMatchResponse)
def recommend_buyers(
    payload: BuyerMatchRequest,
    session: Session = Depends(get_session),
) -> BuyerMatchResponse:
    """재고 로트별 추천 판매처 (SPEC 5.3)."""
    wholesaler = service.get_wholesaler(session, payload.wholesaler_id)
    if wholesaler is None:
        raise HTTPException(status_code=404, detail="도매처를 찾을 수 없습니다")
    crop = service.get_crop(session, payload.crop_id)
    if crop is None:
        raise HTTPException(status_code=404, detail="품목을 찾을 수 없습니다")

    result = service.match_buyers(session, wholesaler, crop, as_of=payload.as_of)
    return BuyerMatchResponse(
        wholesaler_id=result.wholesaler_id,
        wholesaler_name=result.wholesaler_name,
        crop_id=result.crop_id,
        crop_name=result.crop_name,
        as_of=result.as_of,
        total_qty_kg=result.total_qty_kg,
        total_allocated_kg=result.total_allocated_kg,
        total_unallocated_kg=result.total_qty_kg - result.total_allocated_kg,
        lots=[
            LotRecommendationOut(
                lot=_lot_out(item.lot),
                allocated_kg=item.allocated_kg,
                unallocated_kg=item.unallocated_kg,
                recommendations=[_match_out(m) for m in item.matches],
            )
            for item in result.lots
        ],
    )
