"""AI 농산물 시세 예측 API (SPEC 5.1).

HTTP 만 다룬다 — 계산은 전부 ``app/services/price_forecast.py`` 에 있다
(docs/ARCHITECTURE.md 4절).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.price_forecast import (
    HORIZON_DEFAULT,
    HORIZON_MAX,
    PriceForecastOut,
    ShippingWindowIn,
    ShippingWindowOut,
)
from app.services import price_forecast as service

router = APIRouter(prefix="/api/forecast", tags=["price-forecast"])


@router.get(
    "/price",
    response_model=PriceForecastOut,
    summary="일별 시세 예측 + 최근 실적",
)
def get_price_forecast(
    crop_id: int = Query(gt=0, description="품목 ID"),
    region_id: int = Query(gt=0, description="지역 ID"),
    horizon: int = Query(
        HORIZON_DEFAULT, ge=1, le=HORIZON_MAX, description="예측 지평 (일)"
    ),
    as_of: date | None = Query(
        None, description="예측 기준일. 생략하면 시세 이력의 마지막 날"
    ),
    session: Session = Depends(get_session),
) -> PriceForecastOut:
    """차트용 데이터 — 최근 실적 시계열과 ``horizon`` 일치 일별 예측."""
    try:
        result = service.price_forecast(
            session, crop_id=crop_id, region_id=region_id, horizon=horizon, as_of=as_of
        )
    except service.UnknownTargetError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.ForecastRangeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return PriceForecastOut.model_validate(result)


@router.post(
    "/shipping-window",
    response_model=ShippingWindowOut,
    summary="출하일 비교표 (SPEC 5.1)",
)
def post_shipping_window(
    payload: ShippingWindowIn,
    session: Session = Depends(get_session),
) -> ShippingWindowOut:
    """후보 출하일별 예상 가격·매출·시장 상황·시스템 안내를 한 줄씩 돌려준다.

    ``candidate_dates`` 의 **첫 번째 날짜가 기준**이며, 변동률은 그 행 대비다.
    """
    try:
        result = service.shipping_window(
            session,
            crop_id=payload.crop_id,
            region_id=payload.region_id,
            qty_kg=payload.qty_kg,
            candidate_dates=payload.candidate_dates,
            as_of=payload.as_of,
        )
    except service.UnknownTargetError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.ForecastRangeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ShippingWindowOut.model_validate(result)
