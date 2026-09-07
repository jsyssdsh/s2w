"""스마트팜 재배환경 통합관리 · 자동제어 엔진 (SPEC 5.5 / 7.2).

센서값이 REST 든 MQTT 든 **같은 함수**(:func:`ingest_reading`)를 통과한다.
저장 직후 :func:`evaluate_and_control` 이 작물별 ``crop_thresholds`` 와 비교해
펌프·환기팬·조명을 판단하고, 명령마다 ``control_events`` 행을 남긴 뒤
``control/command`` 로 발행한다.

설계 규칙
---------

* **이상이 지속될 때만 작동한다.** SPEC 5.5 의 "이상이 지속되면"을 그대로
  옮겨, 최근 :data:`SUSTAINED_BREACH_READINGS` 회 연속으로 기준을 벗어나야
  가동한다. 스파이크 한 번으로는 아무 일도 일어나지 않는다.
* **히스테리시스.** 켜는 기준과 끄는 기준을 벌려 놓아(release margin) 기준선
  근처에서 장치가 깜빡이지 않는다. 여기에 장치별 :data:`MIN_ON_TIME` 최소
  가동시간이 더해진다.
* **상태는 DB 에서 파생한다.** 별도의 in-memory 상태가 없다. 현재 장치 상태는
  ``control_events`` 의 장치별 최신 행이고, 연속 위반 여부는 최근
  ``sensor_readings`` 다. 서버가 재시작해도, 워커가 여러 개여도 같은 답이 나온다.
* **결정론.** 벽시계를 읽지 않는다. 판단 시각은 방금 들어온 측정값의 ``ts`` 다
  (docs/ARCHITECTURE.md 6절).

환기팬 충돌 해소 순서 (온도 우선)
--------------------------------

환기팬은 온도와 습도 두 항목이 함께 요구하는 유일한 장치라 순서를 못박는다.

1. **온도 상한 초과가 최우선.** 습도가 하한 미만이어도 환기한다. 고온 피해가
   과건조 피해보다 빠르게 작물을 망가뜨린다.
2. 온도가 적정 범위일 때만 **습도 상한 초과**로 환기한다. 단 온도가 하한
   미만이면 환기가 더 냉각시키므로 가동하지 않는다.
3. **습도 하한 미만은 제어 대상이 아니다.** 가습 장치가 없고, 환기는 습도를 더
   낮춘다. 이 경우 할 수 있는 일은 환기를 멈추는 것뿐이다 — 위 1·2 가 참이
   아니면 자연히 정지 조건으로 넘어간다.
4. 정지는 온도·습도가 **둘 다** 여유분만큼 안쪽으로 돌아왔을 때만 한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ControlDevice,
    ControlEvent,
    Crop,
    CropThreshold,
    SensorReading,
    Smartfarm,
)
from app.schemas.smartfarm import SensorReadingIn
from app.services import smartfarm_mqtt

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 제어 상수 — 튜닝 지점은 전부 여기 하나뿐이다.
# --------------------------------------------------------------------------

#: SPEC 5.5 "이상이 지속되면" — 연속 몇 회 위반해야 장치를 가동하는가.
SUSTAINED_BREACH_READINGS = 3

#: 장치 최소 가동시간. 켜진 지 이만큼 지나기 전에는 끄지 않는다.
MIN_ON_TIME = timedelta(minutes=10)

#: 히스테리시스 여유분 — 정지 기준을 가동 기준보다 이만큼 안쪽으로 당긴다.
TEMP_RELEASE_MARGIN_C = 0.5
HUMIDITY_RELEASE_MARGIN_PCT = 2.0
SOIL_RELEASE_MARGIN_PCT = 5.0
#: 조도는 절대값이 아니라 기준 대비 배율로 다룬다 (SPEC 5.5 "설정 기준 이상").
LUX_RELEASE_FACTOR = 1.0

ON = "on"
OFF = "off"

#: 장치가 기본적으로 감시하는 측정 항목. 환기팬은 습도로도 켜질 수 있어서
#: 실제 값은 ``control_events.metric`` 에 기록된 것이 우선이다.
DEVICE_PRIMARY_METRIC: dict[ControlDevice, str] = {
    ControlDevice.FAN: "temp_c",
    ControlDevice.PUMP: "soil_moisture_pct",
    ControlDevice.LIGHT: "lux",
}

#: 측정 항목 → (한글 라벨, 단위, 담당 장치). SPEC 5.5 표의 행 순서다.
METRICS: tuple[tuple[str, str, str, ControlDevice], ...] = (
    ("temp_c", "온도", "℃", ControlDevice.FAN),
    ("humidity_pct", "습도", "%", ControlDevice.FAN),
    ("soil_moisture_pct", "토양수분", "%", ControlDevice.PUMP),
    ("lux", "조도", "lx", ControlDevice.LIGHT),
)

#: 장치 → 사람이 읽는 동작 이름 (대시보드 "자동제어 결과" 열).
_DEVICE_VERB: dict[ControlDevice, tuple[str, str]] = {
    ControlDevice.FAN: ("환기", "환기"),
    ControlDevice.PUMP: ("급수", "급수"),
    ControlDevice.LIGHT: ("조명", "조명"),
}


class SmartfarmNotFound(LookupError):
    """존재하지 않는 스마트팜 id."""


@dataclass(frozen=True)
class DeviceState:
    """``control_events`` 에서 파생한 장치의 현재 상태."""

    device: ControlDevice
    action: str = OFF
    since: datetime | None = None
    metric: str | None = None
    value_before: float | None = None
    value_after: float | None = None
    reason: str = ""
    event_id: int | None = None

    @property
    def is_on(self) -> bool:
        return self.action == ON


@dataclass(frozen=True)
class _Decision:
    """한 장치에 대한 판단 결과."""

    action: str
    metric: str
    reason: str
    value: float


# --------------------------------------------------------------------------
# 조회 헬퍼
# --------------------------------------------------------------------------


def get_smartfarm(session: Session, smartfarm_id: int) -> Smartfarm:
    farm = session.get(Smartfarm, smartfarm_id)
    if farm is None:
        raise SmartfarmNotFound(smartfarm_id)
    return farm


def list_smartfarms(session: Session) -> list[Smartfarm]:
    return list(session.scalars(select(Smartfarm).order_by(Smartfarm.id)))


def get_thresholds(session: Session, crop_id: int) -> CropThreshold | None:
    return session.scalar(select(CropThreshold).where(CropThreshold.crop_id == crop_id))


def crop_name(session: Session, crop_id: int) -> str:
    crop = session.get(Crop, crop_id)
    return crop.name if crop else ""


def recent_readings(
    session: Session, smartfarm_id: int, limit: int
) -> list[SensorReading]:
    """최신순 측정값 ``limit`` 개."""
    return list(
        session.scalars(
            select(SensorReading)
            .where(SensorReading.smartfarm_id == smartfarm_id)
            .order_by(SensorReading.ts.desc(), SensorReading.id.desc())
            .limit(limit)
        )
    )


def latest_reading(session: Session, smartfarm_id: int) -> SensorReading | None:
    found = recent_readings(session, smartfarm_id, 1)
    return found[0] if found else None


def readings_window(
    session: Session, smartfarm_id: int, hours: int
) -> list[SensorReading]:
    """최근 ``hours`` 시간 구간의 측정값 (오래된 것부터).

    기준 시각은 벽시계가 아니라 **가장 최근 측정값의 ts** 다. 시드 데이터가
    ``ANCHOR_DATE`` 에 고정돼 있어도 그래프가 비지 않는다.
    """
    newest = latest_reading(session, smartfarm_id)
    if newest is None:
        return []
    since = newest.ts - timedelta(hours=hours)
    return list(
        session.scalars(
            select(SensorReading)
            .where(
                SensorReading.smartfarm_id == smartfarm_id,
                SensorReading.ts >= since,
            )
            .order_by(SensorReading.ts, SensorReading.id)
        )
    )


def current_device_states(
    session: Session, smartfarm_id: int
) -> dict[ControlDevice, DeviceState]:
    """장치별 최신 ``control_events`` 행에서 현재 상태를 복원한다."""
    states = {device: DeviceState(device=device) for device in ControlDevice}
    events = session.scalars(
        select(ControlEvent)
        .where(ControlEvent.smartfarm_id == smartfarm_id)
        .order_by(ControlEvent.ts.desc(), ControlEvent.id.desc())
    )
    seen: set[ControlDevice] = set()
    for event in events:
        if event.device in seen:
            continue
        seen.add(event.device)
        states[event.device] = DeviceState(
            device=event.device,
            action=event.action,
            since=event.ts,
            metric=event.metric or DEVICE_PRIMARY_METRIC[event.device],
            value_before=event.value_before,
            value_after=event.value_after,
            reason=event.reason,
            event_id=event.id,
        )
        if len(seen) == len(ControlDevice):
            break
    return states


def list_control_events(
    session: Session, smartfarm_id: int, limit: int = 50
) -> list[ControlEvent]:
    return list(
        session.scalars(
            select(ControlEvent)
            .where(ControlEvent.smartfarm_id == smartfarm_id)
            .order_by(ControlEvent.ts.desc(), ControlEvent.id.desc())
            .limit(limit)
        )
    )


# --------------------------------------------------------------------------
# 수집 — REST 와 MQTT 가 공유하는 단 하나의 진입점
# --------------------------------------------------------------------------


def ingest_reading(
    session: Session,
    smartfarm_id: int,
    payload: SensorReadingIn,
    *,
    received_at: datetime | None = None,
) -> tuple[SensorReading, list[ControlEvent]]:
    """측정값을 저장하고 곧바로 자동제어를 판단한다.

    ``POST /api/smartfarm/{id}/readings`` 와 MQTT ``sensor/data`` 구독자가
    똑같이 이 함수를 부른다. 두 경로의 동작이 갈라질 여지를 남기지 않는다.
    """
    get_smartfarm(session, smartfarm_id)  # 없는 스마트팜이면 여기서 끝난다

    ts = payload.ts or received_at or datetime.now()
    reading = SensorReading(
        smartfarm_id=smartfarm_id,
        ts=ts,
        temp_c=payload.temp_c,
        humidity_pct=payload.humidity_pct,
        lux=payload.lux,
        soil_moisture_pct=payload.soil_moisture_pct,
    )
    session.add(reading)
    session.flush()

    events = evaluate_and_control(session, smartfarm_id, now=ts)
    session.commit()
    for event in events:
        _publish(event)
    return reading, events


# --------------------------------------------------------------------------
# 판단 엔진
# --------------------------------------------------------------------------


def evaluate_and_control(
    session: Session, smartfarm_id: int, *, now: datetime | None = None
) -> list[ControlEvent]:
    """최근 측정값을 기준값과 비교해 필요한 제어 명령만 기록한다.

    호출자가 커밋한다. 이미 원하는 상태인 장치는 아무 행도 남기지 않는다.
    """
    farm = get_smartfarm(session, smartfarm_id)
    thresholds = get_thresholds(session, farm.crop_id)
    if thresholds is None:
        logger.warning(
            "smartfarm %s: crop %s 의 crop_thresholds 가 없어 자동제어를 건너뛴다",
            smartfarm_id,
            farm.crop_id,
        )
        return []

    readings = recent_readings(session, smartfarm_id, SUSTAINED_BREACH_READINGS)
    if not readings:
        return []
    latest = readings[0]
    at = now or latest.ts
    states = current_device_states(session, smartfarm_id)

    decisions = [
        _decide_fan(readings, thresholds, states[ControlDevice.FAN]),
        _decide_pump(readings, thresholds, states[ControlDevice.PUMP]),
        _decide_light(readings, thresholds, states[ControlDevice.LIGHT]),
    ]

    events: list[ControlEvent] = []
    for device, decision in zip(
        (ControlDevice.FAN, ControlDevice.PUMP, ControlDevice.LIGHT), decisions
    ):
        event = _apply(session, farm.id, device, decision, states[device], at, latest)
        if event is not None:
            events.append(event)
    session.flush()
    return events


def _sustained(readings: list[SensorReading], attr: str, limit: float, above: bool) -> bool:
    """최근 N 회가 **연속으로** 기준을 벗어났는가."""
    if len(readings) < SUSTAINED_BREACH_READINGS:
        return False
    window = readings[:SUSTAINED_BREACH_READINGS]
    if above:
        return all(getattr(r, attr) > limit for r in window)
    return all(getattr(r, attr) < limit for r in window)


def _decide_fan(
    readings: list[SensorReading], t: CropThreshold, state: DeviceState
) -> _Decision | None:
    """환기팬 — 모듈 docstring 의 온도 우선 순서를 그대로 구현한다."""
    latest = readings[0]

    if _sustained(readings, "temp_c", t.temp_max, above=True):
        return _Decision(
            ON,
            "temp_c",
            f"온도 {latest.temp_c}℃ — 적정 상한 {t.temp_max}℃ 초과, 환기 가동",
            latest.temp_c,
        )

    if (
        _sustained(readings, "humidity_pct", t.humidity_max, above=True)
        and latest.temp_c >= t.temp_min
    ):
        return _Decision(
            ON,
            "humidity_pct",
            f"습도 {latest.humidity_pct}% — 적정 상한 {t.humidity_max}% 초과, 환기 가동",
            latest.humidity_pct,
        )

    released = (
        latest.temp_c <= t.temp_max - TEMP_RELEASE_MARGIN_C
        and latest.humidity_pct <= t.humidity_max - HUMIDITY_RELEASE_MARGIN_PCT
    )
    if state.is_on and released:
        metric = state.metric or "temp_c"
        value = latest.temp_c if metric == "temp_c" else latest.humidity_pct
        return _Decision(
            OFF,
            metric,
            f"온도 {latest.temp_c}℃ · 습도 {latest.humidity_pct}% — "
            "적정 범위 복귀, 환기 중지",
            value,
        )
    return None


def _decide_pump(
    readings: list[SensorReading], t: CropThreshold, state: DeviceState
) -> _Decision | None:
    latest = readings[0]

    if _sustained(readings, "soil_moisture_pct", t.soil_moisture_min, above=False):
        return _Decision(
            ON,
            "soil_moisture_pct",
            f"토양수분 {latest.soil_moisture_pct}% — "
            f"적정 하한 {t.soil_moisture_min}% 미만, 급수 가동",
            latest.soil_moisture_pct,
        )

    released = (
        latest.soil_moisture_pct >= t.soil_moisture_min + SOIL_RELEASE_MARGIN_PCT
    )
    if state.is_on and released:
        return _Decision(
            OFF,
            "soil_moisture_pct",
            f"토양수분 {latest.soil_moisture_pct}% — 적정 수준 회복, 급수 중지",
            latest.soil_moisture_pct,
        )
    return None


def _decide_light(
    readings: list[SensorReading], t: CropThreshold, state: DeviceState
) -> _Decision | None:
    latest = readings[0]

    if _sustained(readings, "lux", t.lux_min, above=False):
        return _Decision(
            ON,
            "lux",
            f"조도 기준의 {lux_pct(latest.lux, t.lux_min)}% — 보광 가동",
            latest.lux,
        )

    if state.is_on and latest.lux >= t.lux_min * LUX_RELEASE_FACTOR:
        return _Decision(
            OFF,
            "lux",
            f"조도 기준의 {lux_pct(latest.lux, t.lux_min)}% — 기준 충족, 조명 소등",
            latest.lux,
        )
    return None


def lux_pct(lux: float, lux_min: float) -> int:
    """조도를 SPEC 5.5 표기(기준의 82%)에 맞춰 백분율로 바꾼다."""
    if lux_min <= 0:
        return 100
    return round(lux / lux_min * 100)


def _apply(
    session: Session,
    smartfarm_id: int,
    device: ControlDevice,
    decision: _Decision | None,
    state: DeviceState,
    at: datetime,
    latest: SensorReading,
) -> ControlEvent | None:
    """판단을 실제 ``control_events`` 행으로 바꾼다 (변화가 있을 때만)."""
    if decision is None or decision.action == state.action:
        return None

    if decision.action == OFF and state.since is not None:
        # 최소 가동시간: 켠 지 얼마 안 됐으면 이번 판단은 보류한다.
        if at - state.since < MIN_ON_TIME:
            logger.debug(
                "smartfarm %s %s: 최소 가동시간 미달, 정지 보류", smartfarm_id, device
            )
            return None

    if decision.action == ON:
        event = _record(
            session,
            smartfarm_id,
            at,
            device,
            ON,
            decision.reason,
            decision.metric,
            value_before=decision.value,
            value_after=None,
        )
        return event

    # 정지: 켤 때의 값을 before 로, 지금 값을 after 로 기록하고
    # 원인이 된 가동 행에도 회복값을 채워 넣는다 (SPEC 5.5 "환기 후 26.5℃").
    value_before = state.value_before
    value_after = decision.value
    if state.event_id is not None:
        on_event = session.get(ControlEvent, state.event_id)
        if on_event is not None and on_event.action == ON:
            on_event.value_after = value_after
    return _record(
        session,
        smartfarm_id,
        at,
        device,
        OFF,
        decision.reason,
        decision.metric,
        value_before=value_before,
        value_after=value_after,
    )


def _record(
    session: Session,
    smartfarm_id: int,
    ts: datetime,
    device: ControlDevice,
    action: str,
    reason: str,
    metric: str | None,
    *,
    value_before: float | None,
    value_after: float | None,
) -> ControlEvent:
    event = ControlEvent(
        smartfarm_id=smartfarm_id,
        ts=ts,
        device=device,
        action=action,
        reason=reason,
        metric=metric,
        value_before=value_before,
        value_after=value_after,
    )
    session.add(event)
    return event


def _publish(event: ControlEvent) -> None:
    """``control/command`` 로 명령을 내보낸다. 브로커가 없으면 조용히 넘어간다."""
    smartfarm_mqtt.publish_command(
        {
            "smartfarm_id": event.smartfarm_id,
            "device": event.device.value,
            "action": event.action,
            "metric": event.metric,
            "reason": event.reason,
            "ts": event.ts.isoformat(),
        }
    )


# --------------------------------------------------------------------------
# 수동 제어 (SPEC 4.5 — 농가가 자동 판단을 덮어쓴다)
# --------------------------------------------------------------------------


def manual_control(
    session: Session,
    smartfarm_id: int,
    device: ControlDevice,
    action: str,
    reason: str | None = None,
    ts: datetime | None = None,
) -> ControlEvent:
    """농가 수동 개입. 연속 위반·히스테리시스·최소 가동시간을 모두 우회한다."""
    get_smartfarm(session, smartfarm_id)
    latest = latest_reading(session, smartfarm_id)
    at = ts or (latest.ts if latest else datetime.now())
    metric = DEVICE_PRIMARY_METRIC[device]
    value = getattr(latest, metric) if latest else None
    verb = _DEVICE_VERB[device][0]
    text = reason or f"수동 제어 — {verb} {'가동' if action == ON else '중지'}"

    event = _record(
        session,
        smartfarm_id,
        at,
        device,
        action,
        text,
        metric,
        value_before=value,
        value_after=None,
    )
    session.commit()
    _publish(event)
    return event


# --------------------------------------------------------------------------
# SPEC 5.5 상태 표
# --------------------------------------------------------------------------


def _target(t: CropThreshold | None, metric: str) -> tuple[float | None, float | None, str]:
    """(하한, 상한, 표시 문자열) — SPEC 5.5 "적정 기준" 열."""
    if t is None:
        return None, None, "기준 미설정"
    if metric == "temp_c":
        return t.temp_min, t.temp_max, f"{t.temp_min:g}~{t.temp_max:g}℃"
    if metric == "humidity_pct":
        return t.humidity_min, t.humidity_max, f"{t.humidity_min:g}~{t.humidity_max:g}%"
    if metric == "soil_moisture_pct":
        return (
            t.soil_moisture_min,
            t.soil_moisture_max,
            f"{t.soil_moisture_min:g}~{t.soil_moisture_max:g}%",
        )
    return t.lux_min, None, "설정 기준 이상"


def _display(metric: str, value: float, t: CropThreshold | None) -> str:
    """SPEC 5.5 "현재 상태" 열 — 조도만 기준 대비 백분율로 쓴다."""
    if metric == "lux":
        if t is None:
            return f"{value:g}lx"
        return f"기준의 {lux_pct(value, t.lux_min)}%"
    if metric == "temp_c":
        return f"{value:g}℃"
    return f"{value:g}%"


def _control_display(
    metric: str, device: ControlDevice, state: DeviceState, t: CropThreshold | None
) -> str:
    """SPEC 5.5 "자동제어 결과" 열.

    회복값이 기록돼 있으면 "환기 후 26.5℃" 처럼 결과를 보여준다. 아직 돌고
    있으면 "환기 가동 중", 개입이 없었으면 "정상 상태 유지" 다.
    """
    verb = _DEVICE_VERB[device][0]
    if state.event_id is None:
        return "정상 상태 유지"
    if state.value_after is not None:
        shown = state.metric or metric
        return f"{verb} 후 {_display(shown, state.value_after, t)}"
    if state.is_on:
        return f"{verb} 가동 중"
    return f"{verb} 완료"


def build_status(session: Session, smartfarm_id: int) -> dict:
    """SPEC 5.5 표(측정 항목/적정 기준/현재 상태/자동제어 결과) + 장치 상태."""
    farm = get_smartfarm(session, smartfarm_id)
    thresholds = get_thresholds(session, farm.crop_id)
    latest = latest_reading(session, smartfarm_id)
    states = current_device_states(session, smartfarm_id)

    metrics: list[dict] = []
    if latest is not None:
        for metric, label, unit, device in METRICS:
            value = getattr(latest, metric)
            low, high, target_display = _target(thresholds, metric)
            in_range = True
            if low is not None:
                in_range = value >= low
            if in_range and high is not None:
                in_range = value <= high
            state = states[device]
            # 환기팬은 두 행(온도·습도)이 공유한다. 지금 그 장치를 움직인
            # 항목이 아니라면 제어 결과 열은 비워 둔다.
            owns = state.event_id is not None and (
                state.metric or DEVICE_PRIMARY_METRIC[device]
            ) == metric
            metrics.append(
                {
                    "metric": metric,
                    "label": label,
                    "unit": unit,
                    "value": value,
                    "display": _display(metric, value, thresholds),
                    "target_min": low,
                    "target_max": high,
                    "target_display": target_display,
                    "in_range": in_range,
                    "device": device,
                    "device_action": state.action if owns else None,
                    "control_display": (
                        _control_display(metric, device, state, thresholds)
                        if owns
                        else "정상 상태 유지"
                    ),
                }
            )

    return {
        "smartfarm_id": farm.id,
        "name": farm.name,
        "farm_id": farm.farm_id,
        "type": farm.type,
        "crop_id": farm.crop_id,
        "crop": crop_name(session, farm.crop_id),
        "ts": latest.ts if latest else None,
        "metrics": metrics,
        "devices": [
            {
                "device": device,
                "action": state.action,
                "since": state.since,
                "reason": state.reason,
            }
            for device, state in states.items()
        ],
    }
