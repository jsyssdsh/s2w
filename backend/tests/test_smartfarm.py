"""스마트팜 자동제어 — SPEC 5.5 워크드 예제와 안전장치 회귀 테스트."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ControlDevice, ControlEvent, CropThreshold, Smartfarm
from app.schemas.smartfarm import SensorReadingIn
from app.seed import ANCHOR_DATE
from app.services import smartfarm as service
from app.services import smartfarm_mqtt

# SPEC 5.5 토마토 기준: 22~27℃ / 60~75% / 토양수분 35~55% / 조도 설정 기준 이상
TOMATO = "1동 토마토 재배구역"
START = datetime.combine(ANCHOR_DATE, datetime.min.time()) + timedelta(days=1)
STEP = timedelta(minutes=10)


@pytest.fixture(scope="module")
def seeded_db_file(tmp_path_factory: pytest.TempPathFactory):
    """시드를 한 번만 채운 SQLite 파일. 테스트마다 여기서 복사해 쓴다."""
    from app.db import build_engine, create_all
    from app.seed import seed_all

    path = tmp_path_factory.mktemp("smartfarm-db") / "seeded.db"
    engine = build_engine(str(path))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        seed_all(session)
    engine.dispose()
    return path


@pytest.fixture
def db_factory(seeded_db_file, tmp_path):
    """테스트 하나만의 DB.

    자동제어는 커밋한다 (MQTT 구독자에게는 요청 스코프가 없다). 그래서 세션
    롤백이 아니라 **파일 복사**로 격리한다 — 시드 비용은 모듈당 한 번뿐이다.
    """
    from app.db import build_engine

    path = tmp_path / "test.db"
    shutil.copy(seeded_db_file, path)
    engine = build_engine(str(path))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def isolated(db_factory: sessionmaker):
    """자기 자신의 센서·제어 이력만 가진 토마토 재배구역.

    시드는 SPEC 5.5 표를 재현하는 측정값과 제어 기록을 이미 갖고 있다.
    엔진 동작을 처음부터 관찰하려면 그것들을 치워야 한다.
    """
    from app.models import SensorReading

    with db_factory() as session:
        farm = session.scalar(select(Smartfarm).where(Smartfarm.name == TOMATO))
        assert farm is not None
        session.execute(delete(SensorReading).where(SensorReading.smartfarm_id == farm.id))
        session.execute(delete(ControlEvent).where(ControlEvent.smartfarm_id == farm.id))
        session.commit()
        yield session, farm.id


def _feed(
    session: Session,
    smartfarm_id: int,
    *,
    count: int,
    start: datetime,
    temp: float = 24.0,
    humidity: float = 68.0,
    lux: float = 18000.0,
    soil: float = 45.0,
    step: timedelta = STEP,
) -> list[ControlEvent]:
    """같은 측정값을 ``count`` 회 흘려 넣고 발생한 제어 이벤트를 모은다."""
    events: list[ControlEvent] = []
    for i in range(count):
        payload = SensorReadingIn(
            ts=start + step * i,
            temp_c=temp,
            humidity_pct=humidity,
            lux=lux,
            soil_moisture_pct=soil,
        )
        _reading, produced = service.ingest_reading(session, smartfarm_id, payload)
        events.extend(produced)
    return events


def _events(session: Session, smartfarm_id: int, device: ControlDevice) -> list[ControlEvent]:
    return list(
        session.scalars(
            select(ControlEvent)
            .where(
                ControlEvent.smartfarm_id == smartfarm_id,
                ControlEvent.device == device,
            )
            .order_by(ControlEvent.ts, ControlEvent.id)
        )
    )


# --------------------------------------------------------------------------
# SPEC 5.5 워크드 예제
# --------------------------------------------------------------------------


def test_spec_scenario_produces_expected_control_events(isolated) -> None:
    """29.4℃ → 환기 → 26.5℃, 토양수분 28% → 급수 → 41%, 조도 82% → 조명 → 101%."""
    session, smartfarm_id = isolated
    limits = session.scalar(
        select(CropThreshold).join(Smartfarm, Smartfarm.crop_id == CropThreshold.crop_id).where(
            Smartfarm.id == smartfarm_id
        )
    )
    assert limits is not None
    lux_min = limits.lux_min

    # 이상 상태가 지속된다 → 환기·급수·조명이 모두 가동한다.
    _feed(
        session,
        smartfarm_id,
        count=service.SUSTAINED_BREACH_READINGS,
        start=START,
        temp=29.4,
        humidity=68.0,
        soil=28.0,
        lux=round(lux_min * 0.82),
    )
    states = service.current_device_states(session, smartfarm_id)
    assert states[ControlDevice.FAN].action == "on"
    assert states[ControlDevice.PUMP].action == "on"
    assert states[ControlDevice.LIGHT].action == "on"

    fan_on = _events(session, smartfarm_id, ControlDevice.FAN)[0]
    assert fan_on.metric == "temp_c"
    assert fan_on.value_before == 29.4
    assert "적정 상한 27.0℃ 초과" in fan_on.reason

    pump_on = _events(session, smartfarm_id, ControlDevice.PUMP)[0]
    assert pump_on.value_before == 28.0
    assert "적정 하한 35.0% 미만" in pump_on.reason

    light_on = _events(session, smartfarm_id, ControlDevice.LIGHT)[0]
    assert "조도 기준의 82%" in light_on.reason

    # 최소 가동시간을 넘긴 뒤 값이 회복된다 → 세 장치 모두 정지한다.
    after = START + STEP * service.SUSTAINED_BREACH_READINGS + service.MIN_ON_TIME
    _feed(
        session,
        smartfarm_id,
        count=1,
        start=after,
        temp=26.5,
        humidity=68.0,
        soil=41.0,
        lux=round(lux_min * 1.01),
    )
    states = service.current_device_states(session, smartfarm_id)
    assert states[ControlDevice.FAN].action == "off"
    assert states[ControlDevice.PUMP].action == "off"
    assert states[ControlDevice.LIGHT].action == "off"

    # SPEC 표의 "환기 후 26.5℃" / "급수 후 41%" 는 가동 행에 채워진 회복값이다.
    session.refresh(fan_on)
    session.refresh(pump_on)
    assert (fan_on.value_before, fan_on.value_after) == (29.4, 26.5)
    assert (pump_on.value_before, pump_on.value_after) == (28.0, 41.0)


def test_humidity_inside_range_produces_no_control(isolated) -> None:
    """습도 68% 는 60~75% 안이므로 아무 명령도 나오지 않는다 (정상 상태 유지)."""
    session, smartfarm_id = isolated
    events = _feed(session, smartfarm_id, count=6, start=START, humidity=68.0)
    assert events == []
    assert _events(session, smartfarm_id, ControlDevice.FAN) == []


def test_single_spike_does_not_trigger_control(isolated) -> None:
    """SPEC 5.5 는 "이상이 지속되면" 이다 — 한 번 튄 값은 무시한다."""
    session, smartfarm_id = isolated
    _feed(session, smartfarm_id, count=2, start=START, temp=24.0)
    spike = _feed(session, smartfarm_id, count=1, start=START + STEP * 2, temp=31.0)
    assert spike == []
    assert service.current_device_states(session, smartfarm_id)[ControlDevice.FAN].action == "off"


# --------------------------------------------------------------------------
# 히스테리시스 / 플래핑 방지
# --------------------------------------------------------------------------


def test_oscillating_value_does_not_flap(isolated) -> None:
    """기준선(27℃) 주위를 오르내려도 명령이 반복해서 나가지 않는다."""
    session, smartfarm_id = isolated

    # 켠다.
    _feed(session, smartfarm_id, count=service.SUSTAINED_BREACH_READINGS, start=START, temp=27.6)
    fan_events = _events(session, smartfarm_id, ControlDevice.FAN)
    assert [e.action for e in fan_events] == ["on"]

    # 히스테리시스 폭(27.0 ~ 26.5) 안에서 20회 진동시킨다.
    at = START + STEP * service.SUSTAINED_BREACH_READINGS + service.MIN_ON_TIME
    for i in range(20):
        temp = 27.2 if i % 2 == 0 else 26.8
        _feed(session, smartfarm_id, count=1, start=at + STEP * i, temp=temp)

    fan_events = _events(session, smartfarm_id, ControlDevice.FAN)
    assert [e.action for e in fan_events] == ["on"], "기준선 근처 진동으로 장치가 깜빡였다"


def test_minimum_on_time_defers_shutdown(isolated) -> None:
    """회복돼도 최소 가동시간 전에는 끄지 않는다."""
    session, smartfarm_id = isolated
    _feed(session, smartfarm_id, count=service.SUSTAINED_BREACH_READINGS, start=START, soil=28.0)
    assert service.current_device_states(session, smartfarm_id)[ControlDevice.PUMP].action == "on"

    turned_on_at = START + STEP * (service.SUSTAINED_BREACH_READINGS - 1)
    too_soon = turned_on_at + service.MIN_ON_TIME / 2
    _feed(session, smartfarm_id, count=1, start=too_soon, soil=45.0)
    assert service.current_device_states(session, smartfarm_id)[ControlDevice.PUMP].action == "on"

    later = too_soon + service.MIN_ON_TIME
    _feed(session, smartfarm_id, count=1, start=later, soil=45.0)
    assert service.current_device_states(session, smartfarm_id)[ControlDevice.PUMP].action == "off"


# --------------------------------------------------------------------------
# 환기팬 충돌 해소 순서 (온도 우선)
# --------------------------------------------------------------------------


def test_high_humidity_alone_starts_fan(isolated) -> None:
    session, smartfarm_id = isolated
    _feed(
        session,
        smartfarm_id,
        count=service.SUSTAINED_BREACH_READINGS,
        start=START,
        temp=24.0,
        humidity=88.0,
    )
    fan_on = _events(session, smartfarm_id, ControlDevice.FAN)[0]
    assert fan_on.metric == "humidity_pct"
    assert "습도 88.0%" in fan_on.reason


def test_temperature_wins_over_low_humidity(isolated) -> None:
    """습도가 하한 미만이어도 고온이면 환기한다 — 문서화된 충돌 해소 순서."""
    session, smartfarm_id = isolated
    _feed(
        session,
        smartfarm_id,
        count=service.SUSTAINED_BREACH_READINGS,
        start=START,
        temp=30.0,
        humidity=45.0,
    )
    fan_on = _events(session, smartfarm_id, ControlDevice.FAN)[0]
    assert fan_on.metric == "temp_c"


def test_low_humidity_alone_never_starts_fan(isolated) -> None:
    """가습 장치가 없다 — 환기하면 더 건조해지므로 아무것도 하지 않는다."""
    session, smartfarm_id = isolated
    events = _feed(session, smartfarm_id, count=6, start=START, temp=24.0, humidity=40.0)
    assert events == []


def test_high_humidity_ignored_when_too_cold(isolated) -> None:
    """온도가 하한 미만이면 환기가 더 냉각시키므로 습도 초과를 무시한다."""
    session, smartfarm_id = isolated
    events = _feed(
        session, smartfarm_id, count=6, start=START, temp=18.0, humidity=88.0
    )
    assert events == []


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@pytest.fixture
def client(db_factory: sessionmaker) -> TestClient:
    from app.db import get_session
    from app.main import app

    def override() -> Session:
        with db_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _tomato(client: TestClient) -> int:
    farms = client.get("/api/smartfarms").json()
    return next(f["id"] for f in farms if f["name"] == TOMATO)


def test_list_smartfarms(client: TestClient) -> None:
    body = client.get("/api/smartfarms").json()
    assert {f["crop"] for f in body} >= {"토마토", "딸기"}


def test_status_matches_spec_table(client: TestClient) -> None:
    """SPEC 5.5 표 그대로: 온도 29.4℃ / 습도 68% 정상 / 토양수분 28% / 조도 82%."""
    response = client.get(f"/api/smartfarm/{_tomato(client)}/status")
    assert response.status_code == 200
    body = response.json()
    assert body["crop"] == "토마토"
    rows = {row["metric"]: row for row in body["metrics"]}
    assert [row["label"] for row in body["metrics"]] == ["온도", "습도", "토양수분", "조도"]

    assert rows["temp_c"]["target_display"] == "22~27℃"
    assert rows["temp_c"]["display"] == "29.4℃"
    assert rows["temp_c"]["in_range"] is False
    assert rows["temp_c"]["control_display"] == "환기 후 26.5℃"

    assert rows["humidity_pct"]["target_display"] == "60~75%"
    assert rows["humidity_pct"]["in_range"] is True
    assert rows["humidity_pct"]["control_display"] == "정상 상태 유지"

    assert rows["soil_moisture_pct"]["target_display"] == "35~55%"
    assert rows["soil_moisture_pct"]["in_range"] is False
    assert rows["soil_moisture_pct"]["control_display"] == "급수 후 41%"

    assert rows["lux"]["target_display"] == "설정 기준 이상"
    assert rows["lux"]["display"] == "기준의 82%"
    assert rows["lux"]["control_display"] == "조명 후 기준의 101%"

    assert {d["device"] for d in body["devices"]} == {"pump", "fan", "light"}


def test_readings_series(client: TestClient) -> None:
    smartfarm_id = _tomato(client)
    body = client.get(f"/api/smartfarm/{smartfarm_id}/readings?metric=temp_c&hours=24").json()
    assert body["metrics"] == ["temp_c"]
    # 시드는 매시 정각 측정값이다. 24시간 창은 경계 포인트를 포함해 25개.
    assert len(body["points"]) == 25
    assert body["points"][0]["humidity_pct"] is None
    assert body["points"][-1]["temp_c"] == 29.4

    everything = client.get(f"/api/smartfarm/{smartfarm_id}/readings?hours=1").json()
    assert everything["points"][-1]["soil_moisture_pct"] == 28.0


def test_readings_series_rejects_unknown_metric(client: TestClient) -> None:
    assert client.get(f"/api/smartfarm/{_tomato(client)}/readings?metric=co2").status_code == 422


def test_controls_log(client: TestClient) -> None:
    body = client.get(f"/api/smartfarm/{_tomato(client)}/controls").json()
    assert {row["device"] for row in body} == {"fan", "pump", "light"}
    assert body[0]["ts"] >= body[-1]["ts"]  # 최신순


def test_manual_override(client: TestClient) -> None:
    smartfarm_id = _tomato(client)
    response = client.post(
        f"/api/smartfarm/{smartfarm_id}/controls",
        json={"device": "pump", "action": "on", "reason": "농가 수동 급수"},
    )
    assert response.status_code == 201
    assert response.json()["reason"] == "농가 수동 급수"

    status_body = client.get(f"/api/smartfarm/{smartfarm_id}/status").json()
    devices = {d["device"]: d for d in status_body["devices"]}
    assert devices["pump"]["action"] == "on"


def test_unknown_smartfarm_is_404(client: TestClient) -> None:
    assert client.get("/api/smartfarm/9999/status").status_code == 404
    assert client.get("/api/smartfarm/9999/controls").status_code == 404
    assert client.get("/api/smartfarm/9999/readings").status_code == 404
    assert (
        client.post(
            "/api/smartfarm/9999/readings",
            json={"temp_c": 24.0, "humidity_pct": 68.0, "lux": 1.0, "soil_moisture_pct": 45.0},
        ).status_code
        == 404
    )


def test_rest_ingest_rejects_impossible_values(client: TestClient) -> None:
    response = client.post(
        f"/api/smartfarm/{_tomato(client)}/readings",
        json={"temp_c": 24.0, "humidity_pct": 480.0, "lux": 1.0, "soil_moisture_pct": 45.0},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# MQTT — 브로커가 없어도 앱이 뜨고 REST 수집이 살아 있어야 한다
# --------------------------------------------------------------------------


def test_app_boots_and_rest_ingest_works_with_broker_down(
    db_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """브로커가 죽어 있어도(=클라이언트 생성 자체가 실패해도) 앱은 뜬다."""
    from app.config import get_settings
    from app.db import get_session
    from app.main import app

    monkeypatch.setenv("MQTT_BROKER_URL", "mqtt://unreachable.invalid:1883")
    get_settings.cache_clear()

    def explode() -> None:
        raise OSError("broker unreachable")

    monkeypatch.setattr(smartfarm_mqtt, "_new_client", explode)
    monkeypatch.setattr(smartfarm_mqtt, "_bridge", None)

    def override() -> Session:
        with db_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app) as c:
            assert smartfarm_mqtt.get_bridge() is None
            assert c.get("/api/health").json() == {"status": "ok"}
            smartfarm_id = _tomato(c)
            response = c.post(
                f"/api/smartfarm/{smartfarm_id}/readings",
                json={
                    "ts": "2026-08-09T00:00:00",
                    "temp_c": 24.0,
                    "humidity_pct": 68.0,
                    "lux": 18000.0,
                    "soil_moisture_pct": 45.0,
                },
            )
            assert response.status_code == 201
            assert response.json()["reading"]["temp_c"] == 24.0
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_publish_command_without_bridge_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smartfarm_mqtt, "_bridge", None)
    assert smartfarm_mqtt.publish_command({"device": "fan"}) is False


def test_bridge_disabled_without_broker_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("MQTT_BROKER_URL", "")
    get_settings.cache_clear()
    monkeypatch.setattr(smartfarm_mqtt, "_bridge", None)
    try:
        assert smartfarm_mqtt.start_from_settings() is None
    finally:
        get_settings.cache_clear()


def test_mqtt_payload_uses_the_same_ingest_path(isolated, monkeypatch) -> None:
    """``sensor/data`` 한 건이 REST 와 똑같이 저장되고 자동제어까지 간다."""
    session, smartfarm_id = isolated

    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return session

        def __exit__(self, *_exc):
            return False

    payload = {
        "smartfarm_id": smartfarm_id,
        "ts": "2026-08-09T00:00:00",
        "temp_c": 29.4,
        "humidity_pct": 68.0,
        "lux": 18000.0,
        "soil_moisture_pct": 45.0,
    }
    assert smartfarm_mqtt.handle_sensor_payload(json.dumps(payload), _Factory()) is True
    assert service.latest_reading(session, smartfarm_id).temp_c == 29.4


def test_mqtt_payload_garbage_is_ignored() -> None:
    assert smartfarm_mqtt.handle_sensor_payload(b"not json") is False
    assert smartfarm_mqtt.handle_sensor_payload(b'{"temp_c": 24.0}') is False
    assert smartfarm_mqtt.handle_sensor_payload(b'{"smartfarm_id": 1}') is False


def test_broker_address_parsing() -> None:
    plain = smartfarm_mqtt.BrokerAddress("mqtt://mosquitto:1883")
    assert (plain.host, plain.port, plain.tls) == ("mosquitto", 1883, False)

    bare = smartfarm_mqtt.BrokerAddress("mosquitto")
    assert (bare.host, bare.port) == ("mosquitto", 1883)

    secure = smartfarm_mqtt.BrokerAddress("mqtts://user:pw@broker.example")
    assert (secure.host, secure.port, secure.tls) == ("broker.example", 8883, True)
    assert (secure.username, secure.password) == ("user", "pw")
