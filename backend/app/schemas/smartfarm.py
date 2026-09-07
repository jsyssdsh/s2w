"""스마트팜 재배환경 통합관리 입출력 스키마 (SPEC 5.5 / 7.2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ControlDevice


class SensorReadingIn(BaseModel):
    """ESP32 가 REST 또는 MQTT ``sensor/data`` 로 보내는 측정값 한 건.

    ``smartfarm_id`` 는 MQTT 페이로드에서만 의미가 있다. REST 로 들어올 때는
    경로 파라미터가 이긴다. ``ts`` 를 주면 그대로 쓰고, 없으면 수신 시각을
    쓴다 — 테스트와 시뮬레이터는 항상 ``ts`` 를 지정해 결정론을 유지한다.
    """

    smartfarm_id: int | None = None
    ts: datetime | None = None
    temp_c: float = Field(ge=-50.0, le=80.0)
    humidity_pct: float = Field(ge=0.0, le=100.0)
    lux: float = Field(ge=0.0)
    soil_moisture_pct: float = Field(ge=0.0, le=100.0)


class SensorReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    smartfarm_id: int
    ts: datetime
    temp_c: float
    humidity_pct: float
    lux: float
    soil_moisture_pct: float


class ControlEventOut(BaseModel):
    """``control/command`` 로 나간 명령 하나의 기록."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    smartfarm_id: int
    ts: datetime
    device: ControlDevice
    action: str
    reason: str
    metric: str | None
    value_before: float | None
    value_after: float | None


class IngestResultOut(BaseModel):
    """측정값 저장 결과 + 그 결과로 실행된 자동제어 명령."""

    reading: SensorReadingOut
    controls: list[ControlEventOut]


class DeviceStateOut(BaseModel):
    device: ControlDevice
    action: str
    since: datetime | None = None
    reason: str = ""


class MetricStatusOut(BaseModel):
    """SPEC 5.5 표의 한 행 — 측정 항목 / 적정 기준 / 현재 상태 / 자동제어 결과."""

    metric: str
    label: str
    unit: str
    value: float
    display: str
    target_min: float | None
    target_max: float | None
    target_display: str
    in_range: bool
    device: ControlDevice | None
    device_action: str | None
    control_display: str


class SmartfarmStatusOut(BaseModel):
    smartfarm_id: int
    name: str
    farm_id: int
    type: str
    crop_id: int
    crop: str
    ts: datetime | None
    metrics: list[MetricStatusOut]
    devices: list[DeviceStateOut]


class SensorPointOut(BaseModel):
    """시계열 한 점. 요청한 metric 만 채워진다 (SPEC 4.5 센서 변화 그래프)."""

    ts: datetime
    temp_c: float | None = None
    humidity_pct: float | None = None
    lux: float | None = None
    soil_moisture_pct: float | None = None


class SensorSeriesOut(BaseModel):
    smartfarm_id: int
    metrics: list[str]
    hours: int
    from_ts: datetime | None
    to_ts: datetime | None
    points: list[SensorPointOut]


class ManualControlIn(BaseModel):
    """농가 수동 개입. 히스테리시스·최소 가동시간을 우회한다."""

    device: ControlDevice
    action: Literal["on", "off"]
    reason: str | None = None
    ts: datetime | None = None


class SmartfarmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    farm_id: int
    parcel_id: int | None
    type: str
    crop_id: int
    crop: str
    started_on: date
    expected_yield_kg: int
