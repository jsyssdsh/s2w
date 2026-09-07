"""지역별 수급 위험 조기 알림 + 대응 방안 (SPEC 5.4)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.supply_risk import AlertOut, SupplyRiskOut
from app.services import supply_risk as service

router = APIRouter(prefix="/api", tags=["supply-risk"])


@router.get("/supply-risk", response_model=SupplyRiskOut)
def supply_risk(
    region_id: int = Query(..., description="지역 id"),
    crop_id: int = Query(..., description="품목 id"),
    window_start: date | None = Query(
        None, description="분석 시작일 (기본: 시드 기준일)"
    ),
    window_end: date | None = Query(
        None,
        description=f"분석 종료일 (기본: 시작일 + {service.DEFAULT_WINDOW_DAYS}일)",
    ),
    session: Session = Depends(get_session),
) -> SupplyRiskOut:
    """물량 내역 · 위험 단계 · 초과 물량 대응 방안."""
    try:
        assessment = service.assess(
            session, region_id, crop_id, window_start, window_end
        )
    except (service.UnknownRegionError, service.UnknownCropError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidWindowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SupplyRiskOut.of(assessment)


@router.get("/alerts", response_model=list[AlertOut])
def alerts(
    region_id: int = Query(..., description="지역 id"),
    as_of: date | None = Query(None, description="기준일 (기본: 시드 기준일)"),
    window_days: int = Query(
        service.DEFAULT_WINDOW_DAYS, ge=1, le=365, description="기준일부터의 분석 기간"
    ),
    session: Session = Depends(get_session),
) -> list[AlertOut]:
    """해당 지역에서 지금 주의·위험 단계인 품목들 (SPEC 4.3 대시보드)."""
    try:
        assessments = service.active_alerts(session, region_id, as_of, window_days)
    except service.UnknownRegionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [AlertOut.of(a) for a in assessments]
