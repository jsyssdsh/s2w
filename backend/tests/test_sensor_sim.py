"""센서 시뮬레이터 → 수집 → 자동제어 통합 테스트 (SPEC 6 / 7.2).

``tools/sensor_sim.py`` 가 만든 스트림을 서버의 수집 경로로 그대로 흘려 넣고,
``sensor_readings`` 행과 ``control_events`` 가 SPEC 5.5 표대로 나오는지 본다.
브로커는 띄우지 않는다 — MQTT 구독자와 REST 핸들러는 같은
``ingest_reading()`` 을 부르므로(docs/ARCHITECTURE.md 11.1) 여기서 검증되는
동작이 곧 브로커 경로의 동작이다. 시뮬레이터가 발행하는 **바이트 그대로**가
서버 구독자에게 받아들여지는지는 마지막 계약 테스트가 따로 확인한다.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ControlDevice,
    ControlEvent,
    CropThreshold,
    SensorReading,
    Smartfarm,
)
from app.schemas.smartfarm import SensorReadingIn
from app.services import smartfarm as service
from app.services import smartfarm_mqtt

# 저장소 루트를 sys.path 에 올려 tools/ 를 임포트한다. pyproject 의
# pythonpath 설정과 같은 목적이지만, 에디터·직접 실행에서도 통하게 둔다.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import sensor_sim  # noqa: E402

TOMATO = "1동 토마토 재배구역"


# --------------------------------------------------------------------------
# 픽스처 — 자동제어는 커밋하므로 세션 롤백이 아니라 DB 파일 복사로 격리한다.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeded_db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from app.db import build_engine, create_all
    from app.seed import seed_all

    path = tmp_path_factory.mktemp("sim-db") / "seeded.db"
    engine = build_engine(str(path))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        seed_all(session)
    engine.dispose()
    return path


@pytest.fixture
def farm(seeded_db_file: Path, tmp_path: Path):
    """센서·제어 이력을 비운 토마토 재배구역과 그 작물의 적정 기준."""
    from app.db import build_engine

    path = tmp_path / "sim.db"
    shutil.copy(seeded_db_file, path)
    engine = build_engine(str(path))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory() as session:
            smartfarm = session.scalar(select(Smartfarm).where(Smartfarm.name == TOMATO))
            assert smartfarm is not None
            session.execute(
                delete(SensorReading).where(SensorReading.smartfarm_id == smartfarm.id)
            )
            session.execute(
                delete(ControlEvent).where(ControlEvent.smartfarm_id == smartfarm.id)
            )
            session.commit()
            limits = session.scalar(
                select(CropThreshold).where(CropThreshold.crop_id == smartfarm.crop_id)
            )
            assert limits is not None
            yield session, smartfarm.id, _thresholds(limits)
    finally:
        engine.dispose()


def _thresholds(row: CropThreshold) -> sensor_sim.Thresholds:
    """DB 의 ``crop_thresholds`` 한 행 → 시뮬레이터가 받는 기준값."""
    return sensor_sim.Thresholds(
        temp_min=row.temp_min,
        temp_max=row.temp_max,
        humidity_min=row.humidity_min,
        humidity_max=row.humidity_max,
        soil_moisture_min=row.soil_moisture_min,
        soil_moisture_max=row.soil_moisture_max,
        lux_min=row.lux_min,
    )


def _run(farm, scenario: str, *, noise: float = 0.0) -> list[dict]:
    """시나리오를 만들어 서버 수집 경로에 그대로 흘려 넣는다."""
    session, smartfarm_id, limits = farm
    payloads = sensor_sim.generate(
        scenario,
        smartfarm_id=smartfarm_id,
        thresholds=limits,
        noise=noise,
    )
    for payload in payloads:
        service.ingest_reading(
            session, smartfarm_id, SensorReadingIn.model_validate(payload)
        )
    return payloads


def _events(session: Session, smartfarm_id: int) -> list[ControlEvent]:
    return list(
        session.scalars(
            select(ControlEvent)
            .where(ControlEvent.smartfarm_id == smartfarm_id)
            .order_by(ControlEvent.ts, ControlEvent.id)
        )
    )


def _stored(session: Session, smartfarm_id: int) -> list[SensorReading]:
    return list(
        session.scalars(
            select(SensorReading)
            .where(SensorReading.smartfarm_id == smartfarm_id)
            .order_by(SensorReading.ts, SensorReading.id)
        )
    )


# --------------------------------------------------------------------------
# 페이로드 계약
# --------------------------------------------------------------------------


def test_payload_matches_the_server_schema() -> None:
    """시뮬레이터의 필드가 ``SensorReadingIn`` 과 정확히 일치한다."""
    payload = sensor_sim.generate("normal")[0]
    assert set(payload) == {
        "smartfarm_id",
        "ts",
        "temp_c",
        "humidity_pct",
        "lux",
        "soil_moisture_pct",
    }
    reading = SensorReadingIn.model_validate(payload)
    assert reading.smartfarm_id == 1
    assert reading.ts == datetime.fromisoformat(payload["ts"])


def test_stream_is_deterministic() -> None:
    """같은 시드는 같은 스트림 — 데모와 테스트가 같은 숫자를 본다."""
    first = sensor_sim.generate("all", seed=7)
    second = sensor_sim.generate("all", seed=7)
    assert first == second
    assert sensor_sim.generate("all", seed=8) != first


def test_rate_and_count_options_shape_the_stream() -> None:
    """``--count`` 로 길이를 강제할 수 있다 (짧게 자르고, 길게 늘린다)."""
    assert len(sensor_sim.generate("heat_spike", count=5)) == 5
    assert len(sensor_sim.generate("heat_spike", count=40)) == 40
    assert len(sensor_sim.generate("heat_spike")) == 11


def test_interval_advances_the_timestamps() -> None:
    payloads = sensor_sim.generate("normal", interval_min=5)
    gaps = {
        datetime.fromisoformat(b["ts"]) - datetime.fromisoformat(a["ts"])
        for a, b in zip(payloads, payloads[1:])
    }
    assert {gap.total_seconds() for gap in gaps} == {300.0}


# --------------------------------------------------------------------------
# 시나리오 → sensor_readings + control_events
# --------------------------------------------------------------------------


def test_readings_are_persisted(farm) -> None:
    session, smartfarm_id, _limits = farm
    payloads = _run(farm, "all")

    rows = _stored(session, smartfarm_id)
    assert len(rows) == len(payloads)
    assert rows[0].temp_c == payloads[0]["temp_c"]
    assert rows[-1].soil_moisture_pct == payloads[-1]["soil_moisture_pct"]


def test_normal_profile_produces_no_control_events(farm) -> None:
    """평상시 프로파일은 네 항목 모두 적정 범위 — 정상 상태 유지."""
    session, smartfarm_id, _limits = farm
    _run(farm, "normal")

    assert _events(session, smartfarm_id) == []
    assert len(_stored(session, smartfarm_id)) == 12


def test_normal_profile_stays_inside_the_crop_thresholds(farm) -> None:
    """잡음을 켜도 평상시 값은 기준을 넘지 않는다."""
    _session, smartfarm_id, limits = farm
    for payload in sensor_sim.generate(
        "normal", smartfarm_id=smartfarm_id, thresholds=limits, noise=0.5
    ):
        assert limits.temp_min < payload["temp_c"] < limits.temp_max
        assert limits.humidity_min < payload["humidity_pct"] < limits.humidity_max
        assert payload["soil_moisture_pct"] > limits.soil_moisture_min
        assert payload["lux"] > limits.lux_min


def test_heat_spike_triggers_ventilation(farm) -> None:
    """SPEC 5.5: 29.4℃ → 환기 → 26.5℃ 대의 회복값으로 정지."""
    session, smartfarm_id, limits = farm
    _run(farm, "heat_spike")

    fan = [e for e in _events(session, smartfarm_id) if e.device == ControlDevice.FAN]
    assert [e.action for e in fan] == ["on", "off"]
    assert fan[0].metric == "temp_c"
    assert fan[0].value_before == 29.4
    assert f"적정 상한 {limits.temp_max}℃ 초과" in fan[0].reason
    assert fan[0].value_after == 26.3  # 정지 기준(상한 − 0.5℃) 아래로 회복

    # 환기 말고는 아무 장치도 건드리지 않는다.
    assert {e.device for e in _events(session, smartfarm_id)} == {ControlDevice.FAN}


def test_soil_dry_down_triggers_irrigation(farm) -> None:
    """SPEC 5.5: 토양수분 28% → 급수 → 41%."""
    session, smartfarm_id, limits = farm
    _run(farm, "soil_dry_down")

    pump = [e for e in _events(session, smartfarm_id) if e.device == ControlDevice.PUMP]
    assert [e.action for e in pump] == ["on", "off"]
    assert pump[0].metric == "soil_moisture_pct"
    assert (pump[0].value_before, pump[0].value_after) == (28.0, 41.0)
    assert f"적정 하한 {limits.soil_moisture_min}% 미만" in pump[0].reason

    assert {e.device for e in _events(session, smartfarm_id)} == {ControlDevice.PUMP}


def test_dusk_triggers_supplemental_light(farm) -> None:
    """SPEC 5.5: 조도 기준의 82% → 조명 → 101%."""
    session, smartfarm_id, _limits = farm
    _run(farm, "dusk")

    light = [
        e for e in _events(session, smartfarm_id) if e.device == ControlDevice.LIGHT
    ]
    assert [e.action for e in light] == ["on", "off"]
    assert "조도 기준의 82%" in light[0].reason
    assert "기준의 101%" in light[1].reason

    assert {e.device for e in _events(session, smartfarm_id)} == {ControlDevice.LIGHT}


def test_all_scenario_exercises_every_control_path(farm) -> None:
    """``--scenario all`` 한 번으로 펌프·환기팬·조명이 모두 켜졌다 꺼진다."""
    session, smartfarm_id, _limits = farm
    payloads = _run(farm, "all")

    events = _events(session, smartfarm_id)
    assert len(_stored(session, smartfarm_id)) == len(payloads)

    by_device = {device: [] for device in ControlDevice}
    for event in events:
        by_device[event.device].append(event.action)
    assert by_device[ControlDevice.FAN] == ["on", "off"]
    assert by_device[ControlDevice.PUMP] == ["on", "off"]
    assert by_device[ControlDevice.LIGHT] == ["on", "off"]

    # 끝나고 나면 모든 장치가 꺼져 있다.
    states = service.current_device_states(session, smartfarm_id)
    assert {state.action for state in states.values()} == {"off"}


def test_scenarios_survive_sensor_noise(farm) -> None:
    """기본 잡음(±0.1)이 붙어도 제어 판단은 그대로다."""
    session, smartfarm_id, _limits = farm
    _run(farm, "all", noise=sensor_sim.DEFAULT_NOISE)

    by_device = {device: [] for device in ControlDevice}
    for event in _events(session, smartfarm_id):
        by_device[event.device].append(event.action)
    assert by_device[ControlDevice.FAN] == ["on", "off"]
    assert by_device[ControlDevice.PUMP] == ["on", "off"]
    assert by_device[ControlDevice.LIGHT] == ["on", "off"]


def test_unknown_scenario_is_rejected() -> None:
    with pytest.raises(ValueError, match="모르는 시나리오"):
        sensor_sim.generate("monsoon")


# --------------------------------------------------------------------------
# 브로커 경로 계약 — 시뮬레이터가 발행하는 바이트 그대로를 서버가 받는다
# --------------------------------------------------------------------------


def test_published_bytes_are_accepted_by_the_mqtt_subscriber(farm) -> None:
    """시뮬레이터가 ``sensor/data`` 로 내보내는 JSON 을 구독자가 그대로 삼킨다."""
    session, smartfarm_id, limits = farm

    class _Factory:
        """구독자가 여는 세션을 테스트 세션으로 바꿔치기한다."""

        def __call__(self):
            return self

        def __enter__(self):
            return session

        def __exit__(self, *_exc):
            return False

    payloads = sensor_sim.generate(
        "heat_spike", smartfarm_id=smartfarm_id, thresholds=limits, noise=0.0
    )
    for payload in payloads:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        assert smartfarm_mqtt.handle_sensor_payload(raw, _Factory()) is True

    assert len(_stored(session, smartfarm_id)) == len(payloads)
    fan = [e for e in _events(session, smartfarm_id) if e.device == ControlDevice.FAN]
    assert [e.action for e in fan] == ["on", "off"]


def test_mqtt_publisher_uses_the_contract_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    """토픽 이름과 QoS 는 서버 브리지와 같아야 한다 (ARCHITECTURE 11.1)."""
    assert sensor_sim.SENSOR_TOPIC == smartfarm_mqtt.SENSOR_TOPIC

    sent: list[tuple[str, str, int]] = []

    class _FakeInfo:
        def wait_for_publish(self, timeout: float | None = None) -> None:
            return None

    class _FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def username_pw_set(self, *_args) -> None:
            pass

        def tls_set(self) -> None:
            pass

        def connect(self, *_args) -> None:
            pass

        def loop_start(self) -> None:
            pass

        def loop_stop(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

        def publish(self, topic: str, payload: str, qos: int = 0) -> _FakeInfo:
            sent.append((topic, payload, qos))
            return _FakeInfo()

    import paho.mqtt.client as paho

    monkeypatch.setattr(paho, "Client", _FakeClient)

    publisher = sensor_sim.MqttPublisher("mqtt://mosquitto:1883")
    assert (publisher.host, publisher.port) == ("mosquitto", 1883)
    with publisher as connected:
        connected.send(sensor_sim.generate("normal")[0])

    topic, payload, qos = sent[0]
    assert topic == "sensor/data"
    assert qos == 1
    assert json.loads(payload)["smartfarm_id"] == 1


def test_broker_url_forms_are_parsed_like_the_server() -> None:
    """서버의 ``BrokerAddress`` 와 같은 URL 문법을 받아들인다."""
    for url, host, port in (
        ("mqtt://mosquitto:1883", "mosquitto", 1883),
        ("localhost", "localhost", 1883),
        ("mqtts://broker.example:8883", "broker.example", 8883),
    ):
        publisher = sensor_sim.MqttPublisher(url)
        server_side = smartfarm_mqtt.BrokerAddress(url)
        assert (publisher.host, publisher.port) == (host, port)
        assert (server_side.host, server_side.port) == (host, port)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_print_transport_emits_one_json_line_per_reading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = sensor_sim.main(
        [
            "--scenario",
            "dusk",
            "--transport",
            "print",
            "--rate",
            "0",
            "--noise",
            "0",
            "--no-fetch-thresholds",
        ]
    )
    assert exit_code == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == len(sensor_sim.generate("dusk"))
    assert json.loads(lines[0])["smartfarm_id"] == 1


def test_cli_rejects_an_unknown_scenario() -> None:
    with pytest.raises(SystemExit):
        sensor_sim.main(["--scenario", "monsoon", "--transport", "print"])


def test_fetch_thresholds_falls_back_when_the_server_is_unreachable() -> None:
    assert sensor_sim.fetch_thresholds("http://127.0.0.1:1", 1) is None
