"""스마트팜 재배환경 통합관리 · 자동제어 API (SPEC 5.5 / 7.2)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.smartfarm import (
    ControlEventOut,
    IngestResultOut,
    ManualControlIn,
    SensorPointOut,
    SensorReadingIn,
    SensorSeriesOut,
    SmartfarmOut,
    SmartfarmStatusOut,
)
from app.services import smartfarm as service
from app.services import smartfarm_mqtt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["smartfarm"])

METRIC_NAMES = [metric for metric, _label, _unit, _device in service.METRICS]


def _load(session: Session, smartfarm_id: int) -> None:
    try:
        service.get_smartfarm(session, smartfarm_id)
    except service.SmartfarmNotFound:
        raise HTTPException(status_code=404, detail="스마트팜을 찾을 수 없습니다") from None


@router.get("/smartfarms", response_model=list[SmartfarmOut])
def list_smartfarms(session: Session = Depends(get_session)) -> list[SmartfarmOut]:
    """재배구역 목록 — 대시보드와 유휴토지 상세 화면의 진입점."""
    return [
        SmartfarmOut(
            id=farm.id,
            name=farm.name,
            farm_id=farm.farm_id,
            parcel_id=farm.parcel_id,
            type=farm.type,
            crop_id=farm.crop_id,
            crop=service.crop_name(session, farm.crop_id),
            started_on=farm.started_on,
            expected_yield_kg=farm.expected_yield_kg,
        )
        for farm in service.list_smartfarms(session)
    ]


@router.post(
    "/smartfarm/{smartfarm_id}/readings",
    response_model=IngestResultOut,
    status_code=status.HTTP_201_CREATED,
)
def create_reading(
    smartfarm_id: int,
    payload: SensorReadingIn,
    session: Session = Depends(get_session),
) -> IngestResultOut:
    """센서 측정값 수집 (REST 경로).

    MQTT ``sensor/data`` 구독자와 **같은** 서비스 함수를 호출하므로 브로커가
    죽어 있어도 수집과 자동제어가 그대로 동작한다.
    """
    try:
        reading, events = service.ingest_reading(session, smartfarm_id, payload)
    except service.SmartfarmNotFound:
        raise HTTPException(status_code=404, detail="스마트팜을 찾을 수 없습니다") from None
    return IngestResultOut(
        reading=reading,
        controls=[ControlEventOut.model_validate(e) for e in events],
    )


@router.get("/smartfarm/{smartfarm_id}/status", response_model=SmartfarmStatusOut)
def get_status(
    smartfarm_id: int, session: Session = Depends(get_session)
) -> SmartfarmStatusOut:
    """SPEC 5.5 표: 측정 항목 / 적정 기준 / 현재 상태 / 자동제어 결과."""
    try:
        return SmartfarmStatusOut.model_validate(service.build_status(session, smartfarm_id))
    except service.SmartfarmNotFound:
        raise HTTPException(status_code=404, detail="스마트팜을 찾을 수 없습니다") from None


@router.get("/smartfarm/{smartfarm_id}/readings", response_model=SensorSeriesOut)
def get_readings(
    smartfarm_id: int,
    metric: str | None = Query(default=None, description="temp_c / humidity_pct / lux / soil_moisture_pct"),
    hours: int = Query(default=24, ge=1, le=720),
    session: Session = Depends(get_session),
) -> SensorSeriesOut:
    """센서 변화 그래프용 시계열 (SPEC 4.5).

    구간 기준은 벽시계가 아니라 마지막 측정값의 시각이다 —
    시드 데이터(ANCHOR_DATE)로도 그래프가 비지 않는다.
    """
    _load(session, smartfarm_id)
    if metric is not None and metric not in METRIC_NAMES:
        raise HTTPException(
            status_code=422, detail=f"metric 은 {', '.join(METRIC_NAMES)} 중 하나여야 합니다"
        )
    wanted = [metric] if metric else METRIC_NAMES
    rows = service.readings_window(session, smartfarm_id, hours)
    points = [
        SensorPointOut(ts=row.ts, **{name: getattr(row, name) for name in wanted})
        for row in rows
    ]
    return SensorSeriesOut(
        smartfarm_id=smartfarm_id,
        metrics=wanted,
        hours=hours,
        from_ts=points[0].ts if points else None,
        to_ts=points[-1].ts if points else None,
        points=points,
    )


@router.get("/smartfarm/{smartfarm_id}/controls", response_model=list[ControlEventOut])
def get_controls(
    smartfarm_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[ControlEventOut]:
    """자동제어 실행 기록 (최신순)."""
    _load(session, smartfarm_id)
    return [
        ControlEventOut.model_validate(e)
        for e in service.list_control_events(session, smartfarm_id, limit)
    ]


@router.post(
    "/smartfarm/{smartfarm_id}/controls",
    response_model=ControlEventOut,
    status_code=status.HTTP_201_CREATED,
)
def create_control(
    smartfarm_id: int,
    payload: ManualControlIn,
    session: Session = Depends(get_session),
) -> ControlEventOut:
    """수동 제어 — 자동 판단(연속 위반·히스테리시스·최소 가동시간)을 우회한다."""
    try:
        event = service.manual_control(
            session,
            smartfarm_id,
            payload.device,
            payload.action,
            payload.reason,
            payload.ts,
        )
    except service.SmartfarmNotFound:
        raise HTTPException(status_code=404, detail="스마트팜을 찾을 수 없습니다") from None
    return ControlEventOut.model_validate(event)


# --------------------------------------------------------------------------
# MQTT 브리지 생명주기
#
# app/main.py 에는 include_router 한 줄만 둔다는 규약(ARCHITECTURE 4절)을
# 지키려고, 브리지 시작/정지는 이 라우터 자신의 startup/shutdown 훅에 건다.
# FastAPI 는 커스텀 lifespan 과 별개로 이 훅들을 실행한다.
# MQTT_BROKER_URL 이 비어 있으면 두 훅 모두 아무 일도 하지 않는다.
# --------------------------------------------------------------------------


def _start_mqtt_bridge() -> None:
    smartfarm_mqtt.start_from_settings()


def _stop_mqtt_bridge() -> None:
    smartfarm_mqtt.stop_bridge()


router.add_event_handler("startup", _start_mqtt_bridge)
router.add_event_handler("shutdown", _stop_mqtt_bridge)
