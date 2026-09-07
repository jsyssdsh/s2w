"""농가 맞춤형 도매처 추천과 거래 피드백 루프 (SPEC 5.2 / 7.1).

HTTP 계층만 둔다. 계산은 전부 ``app/services/wholesaler_rec.py`` 에 있다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.wholesaler_rec import (
    DealIn,
    DealOut,
    WholesalerRecommendationIn,
    WholesalerRecommendationOut,
)
from app.services import wholesaler_rec as service

router = APIRouter(prefix="/api", tags=["wholesaler-rec"])


@router.post("/recommendations/wholesalers", response_model=WholesalerRecommendationOut)
def recommend_wholesalers(
    payload: WholesalerRecommendationIn,
    session: Session = Depends(get_session),
) -> WholesalerRecommendationOut:
    """도매처별 예상 순수익을 계산해 순위와 근거를 돌려준다."""
    try:
        result = service.recommend_wholesalers(
            session,
            farm_id=payload.farm_id,
            crop_id=payload.crop_id,
            qty_kg=payload.qty_kg,
            ship_date=payload.ship_date,
            use_forecast=payload.use_forecast,
            limit=payload.limit,
        )
    except service.RecommendationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WholesalerRecommendationOut.from_domain(result)


@router.post("/deals", response_model=DealOut, status_code=201)
def create_deal(
    payload: DealIn, session: Session = Depends(get_session)
) -> DealOut:
    """농가가 실제로 선택한 거래처를 기록한다 — 다음 추천의 학습 신호."""
    try:
        deal = service.record_deal(
            session,
            shipment_id=payload.shipment_id,
            wholesaler_id=payload.wholesaler_id,
            status=payload.status,
            agreed_price_krw=payload.agreed_price_krw,
            decided_on=payload.decided_on,
        )
    except service.RecommendationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DealOut.model_validate(deal)


@router.get("/deals", response_model=list[DealOut])
def list_deals(
    shipment_id: int | None = Query(default=None),
    wholesaler_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[DealOut]:
    """기록된 거래 이력. 대시보드가 피드백 루프를 보여줄 때 쓴다."""
    deals = service.list_deals(
        session, shipment_id=shipment_id, wholesaler_id=wholesaler_id
    )
    return [DealOut.model_validate(d) for d in deals]
