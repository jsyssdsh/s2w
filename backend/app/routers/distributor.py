"""SPEC 4.3 유통업체 대시보드 — HTTP 계층.

계산은 전부 ``app/services/distributor.py`` 에 있다. 여기서는 조회·검증과
표시용 반올림만 한다 (ARCHITECTURE 5절: 반올림은 표현 계층에서).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.distributor import (
    DealRequestIn,
    DealRequestOut,
    FarmRecommendationOut,
    FarmRecommendationResponse,
    MarketPointOut,
    MarketRowOut,
    MarketSnapshotOut,
    RecommendationSummaryOut,
    WholesalerOut,
)
from app.services import distributor as service
from app.services.buyer_match import GRADE_LABEL

router = APIRouter(prefix="/api/distributor", tags=["distributor"])

_DISTANCE_DP = 1
_PCT_DP = 2


def _wholesaler_out(info: service.WholesalerInfo) -> WholesalerOut:
    return WholesalerOut.model_validate(info)


def _row_out(row: service.FarmRecommendation) -> FarmRecommendationOut:
    return FarmRecommendationOut(
        shipment_id=row.shipment_id,
        farm_id=row.farm_id,
        farm_name=row.farm_name,
        region_id=row.region_id,
        region_name=row.region_name,
        crop_id=row.crop_id,
        crop_name=row.crop_name,
        grade=row.grade,
        grade_label=GRADE_LABEL[row.grade],
        ship_date=row.ship_date,
        qty_kg=row.qty_kg,
        purchasable_kg=row.purchasable_kg,
        unsold_kg=row.unsold_kg,
        distance_km=round(row.distance_km, _DISTANCE_DP),
        transport_cost_krw=row.transport_cost_krw,
        market_price_per_kg=row.market_price_per_kg,
        graded_price_per_kg=row.graded_price_per_kg,
        recommended_price_per_kg=row.recommended_price_per_kg,
        offer_pct=round(row.offer_ratio * 100, _PCT_DP),
        purchase_cost_krw=row.purchase_cost_krw,
        resale_revenue_krw=row.resale_revenue_krw,
        fee_krw=row.fee_krw,
        expected_net_profit_krw=row.expected_net_profit_krw,
        margin_pct=round(row.margin_rate * 100, _PCT_DP),
        price_source=row.price_source,
        requested=row.requested,
        recommended=row.recommended,
        reason=row.reason,
    )


@router.get("/wholesalers", response_model=list[WholesalerOut])
def list_wholesalers(session: Session = Depends(get_session)) -> list[WholesalerOut]:
    """대시보드의 도매처 선택기 — 로그인이 붙기 전까지의 진입점."""
    return [_wholesaler_out(w) for w in service.list_wholesalers(session)]


@router.get("/farm-recommendations", response_model=FarmRecommendationResponse)
def farm_recommendations(
    wholesaler_id: int = Query(description="도매처 id"),
    crop_id: int | None = Query(default=None, description="품목으로 거르기"),
    as_of: date = Query(default=service.DEFAULT_AS_OF, description="기준일"),
    window_days: int = Query(
        default=service.DEFAULT_WINDOW_DAYS, ge=1, le=365, description="기준일부터의 분석 기간"
    ),
    use_forecast: bool = Query(
        default=False,
        description="권장 거래가의 기준 단가로 SPEC 5.1 예측 시세를 쓴다. "
        "모델 캐시가 비어 있으면 품목당 수십 초가 걸린다.",
    ),
    session: Session = Depends(get_session),
) -> FarmRecommendationResponse:
    """AI 추천 농가 리스트 + SPEC 4.3 요약 타일."""
    wholesaler = service.get_wholesaler(session, wholesaler_id)
    if wholesaler is None:
        raise HTTPException(status_code=404, detail="도매처를 찾을 수 없습니다")
    if crop_id is not None and service.get_crop(session, crop_id) is None:
        raise HTTPException(status_code=404, detail="품목을 찾을 수 없습니다")

    result = service.recommend_farms(
        session,
        wholesaler,
        crop_id=crop_id,
        as_of=as_of,
        window_days=window_days,
        use_forecast=use_forecast,
    )
    return FarmRecommendationResponse(
        wholesaler=_wholesaler_out(result.wholesaler),
        as_of=result.as_of,
        window_end=result.window_end,
        summary=RecommendationSummaryOut.model_validate(result.summary),
        rows=[_row_out(r) for r in result.rows],
    )


@router.post("/deal-requests", response_model=DealRequestOut, status_code=201)
def create_deal_request(
    payload: DealRequestIn,
    session: Session = Depends(get_session),
) -> DealRequestOut:
    """"거래 요청 보내기" — ``deals`` 에 ``proposed`` 행을 남긴다 (멱등)."""
    try:
        result = service.request_deal(
            session,
            wholesaler_id=payload.wholesaler_id,
            shipment_id=payload.shipment_id,
            unit_price_krw=payload.unit_price_krw,
            as_of=payload.as_of or service.DEFAULT_AS_OF,
        )
    except service.UnknownWholesalerError:
        raise HTTPException(status_code=404, detail="도매처를 찾을 수 없습니다") from None
    except service.UnknownShipmentError:
        raise HTTPException(status_code=404, detail="출하 정보를 찾을 수 없습니다") from None
    except service.ShipmentUnavailableError:
        raise HTTPException(
            status_code=409, detail="이미 거래가 확정된 출하입니다"
        ) from None

    message = (
        f"{result.farm_name}에 {result.crop_name} {result.qty_kg:,}kg "
        f"거래 요청을 보냈습니다."
        if result.created
        else f"{result.farm_name}에 보낸 거래 요청을 갱신했습니다."
    )
    return DealRequestOut(
        id=result.id,
        shipment_id=result.shipment_id,
        wholesaler_id=result.wholesaler_id,
        wholesaler_name=result.wholesaler_name,
        farm_name=result.farm_name,
        crop_name=result.crop_name,
        qty_kg=result.qty_kg,
        unit_price_krw=result.unit_price_krw,
        agreed_price_krw=result.agreed_price_krw,
        status=result.status,
        created=result.created,
        message=message,
    )


@router.get("/market", response_model=MarketSnapshotOut)
def market(
    region_id: int | None = Query(default=None, description="지역 id (생략 시 첫 지역)"),
    as_of: date | None = Query(default=None, description="기준일 (생략 시 시세 이력의 마지막 날)"),
    lookback_days: int = Query(
        default=service.DEFAULT_MARKET_LOOKBACK_DAYS,
        ge=1,
        le=365,
        description="등락률을 재는 기간",
    ),
    session: Session = Depends(get_session),
) -> MarketSnapshotOut:
    """실시간 시장 분석 — 품목별 가격/수요 등락률 (SPEC 4.3)."""
    target_id = region_id if region_id is not None else service.default_region_id(session)
    if target_id is None or service.get_region(session, target_id) is None:
        raise HTTPException(status_code=404, detail="지역을 찾을 수 없습니다")

    snapshot = service.market_snapshot(
        session, target_id, as_of=as_of, lookback_days=lookback_days
    )
    return MarketSnapshotOut(
        region_id=snapshot.region_id,
        region_name=snapshot.region_name,
        as_of=snapshot.as_of,
        lookback_days=snapshot.lookback_days,
        rows=[
            MarketRowOut(
                crop_id=row.crop_id,
                crop_name=row.crop_name,
                unit=row.unit,
                price_per_kg=row.price_per_kg,
                previous_price_per_kg=row.previous_price_per_kg,
                price_change_pct=round(row.price_change_pct, _PCT_DP),
                volume_kg=row.volume_kg,
                previous_volume_kg=row.previous_volume_kg,
                demand_change_pct=round(row.demand_change_pct, _PCT_DP),
                trend=row.trend,
                series=[MarketPointOut.model_validate(p) for p in row.series],
            )
            for row in snapshot.rows
        ],
    )
