"""MQTT 브리지 — ESP32 ↔ 서버 (SPEC 6.2 / 7.2).

ESP32 는 ``sensor/data`` 로 측정값을 올리고, 서버는 ``control/command`` 로
급수·환기·조명 명령을 내린다. 브로커 주소는 ``MQTT_BROKER_URL`` 이며 비어
있으면 브리지 전체가 비활성(REST 전용)이다.

**브로커가 없어도 앱은 뜬다.** 연결은 ``connect_async`` + 백그라운드 루프라
시작 시 블로킹하지 않고, paho 가 지수 백오프로 재접속을 계속한다. 이 모듈의
공개 함수는 어떤 경우에도 예외를 밖으로 내보내지 않는다 — 자동제어가 죽어도
REST API 는 계속 서비스돼야 한다 (bead 인수조건).

paho-mqtt 는 :func:`_new_client` 안에서 지연 임포트한다. 패키지가 없는
환경에서도 임포트 단계에서 앱이 무너지지 않는다.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings

logger = logging.getLogger(__name__)

SENSOR_TOPIC = "sensor/data"
COMMAND_TOPIC = "control/command"

#: 재접속 백오프 (초). paho 가 min → max 로 지수 증가시킨다.
RECONNECT_DELAY_MIN_S = 1
RECONNECT_DELAY_MAX_S = 60

DEFAULT_PORT = 1883
DEFAULT_TLS_PORT = 8883


class BrokerAddress:
    """``mqtt://user:pass@host:1883`` 를 paho 인자로 쪼갠 결과."""

    def __init__(self, url: str) -> None:
        parsed = urlparse(url if "//" in url else f"mqtt://{url}")
        self.scheme = (parsed.scheme or "mqtt").lower()
        self.tls = self.scheme in ("mqtts", "ssl", "mqtt+ssl")
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or (DEFAULT_TLS_PORT if self.tls else DEFAULT_PORT)
        self.username = parsed.username
        self.password = parsed.password

    def __str__(self) -> str:  # pragma: no cover - 로그 표현용
        return f"{self.scheme}://{self.host}:{self.port}"


def _new_client() -> Any:
    """paho 클라이언트를 지연 임포트해서 만든다 (패키지가 없으면 ImportError)."""
    from paho.mqtt.client import CallbackAPIVersion, Client

    return Client(CallbackAPIVersion.VERSION2)


class MqttBridge:
    """``sensor/data`` 구독 + ``control/command`` 발행."""

    def __init__(self, address: BrokerAddress, session_factory: Any | None = None) -> None:
        self.address = address
        self._session_factory = session_factory
        self._client: Any | None = None
        self._lock = threading.Lock()

    # -- 생명주기 ---------------------------------------------------------

    def start(self) -> bool:
        """브로커 연결을 백그라운드로 시작한다. 실패해도 False 를 돌려줄 뿐이다."""
        with self._lock:
            if self._client is not None:
                return True
            try:
                client = _new_client()
                if self.address.username:
                    client.username_pw_set(self.address.username, self.address.password)
                if self.address.tls:
                    client.tls_set()
                client.reconnect_delay_set(
                    min_delay=RECONNECT_DELAY_MIN_S, max_delay=RECONNECT_DELAY_MAX_S
                )
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect
                client.on_message = self._on_message
                # connect_async 는 즉시 반환한다. 실제 접속과 재시도는
                # loop_start 가 띄운 스레드가 백오프를 두고 계속한다.
                client.connect_async(self.address.host, self.address.port)
                client.loop_start()
            except Exception:  # noqa: BLE001 - 자동제어 실패가 앱을 막지 않는다
                logger.exception("MQTT 브리지 시작 실패 (%s) — REST 전용으로 계속한다", self.address)
                self._client = None
                return False
            self._client = client
            logger.info("MQTT 브리지 시작: %s (구독 %s)", self.address, SENSOR_TOPIC)
            return True

    def stop(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001 - 종료 경로에서는 삼킨다
            logger.warning("MQTT 브리지 종료 중 오류", exc_info=True)

    @property
    def running(self) -> bool:
        return self._client is not None

    # -- 발행 -------------------------------------------------------------

    def publish_command(self, command: dict[str, Any]) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            client.publish(COMMAND_TOPIC, json.dumps(command, ensure_ascii=False), qos=1)
        except Exception:  # noqa: BLE001 - 브로커가 끊겨도 DB 기록은 남는다
            logger.warning("control/command 발행 실패: %s", command, exc_info=True)
            return False
        return True

    # -- 콜백 -------------------------------------------------------------

    def _on_connect(self, client: Any, _userdata: Any, _flags: Any, reason: Any, *_: Any) -> None:
        if getattr(reason, "is_failure", False):
            logger.warning("MQTT 연결 거부 (%s): %s — 백오프 후 재시도", self.address, reason)
            return
        logger.info("MQTT 연결됨 (%s)", self.address)
        client.subscribe(SENSOR_TOPIC, qos=1)

    def _on_disconnect(self, _client: Any, _userdata: Any, *args: Any) -> None:
        logger.warning("MQTT 연결 끊김 (%s) — 자동 재접속 대기", self.address)

    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        """``sensor/data`` 페이로드를 REST 와 같은 수집 경로로 흘려보낸다."""
        try:
            handle_sensor_payload(message.payload, session_factory=self._session_factory)
        except Exception:  # noqa: BLE001 - 잘못된 한 건이 구독을 죽이면 안 된다
            logger.exception("sensor/data 처리 실패")


def handle_sensor_payload(
    payload: bytes | str, session_factory: Any | None = None
) -> bool:
    """MQTT 로 받은 JSON 한 건을 저장한다. 성공하면 True.

    REST 핸들러와 **같은** ``ingest_reading`` 을 부른다. 이 함수가 두 경로가
    갈라지지 않게 붙잡아 두는 이음매다.
    """
    # 순환 임포트 방지: 서비스가 이 모듈을 발행용으로 임포트한다.
    from app.db import SessionLocal
    from app.schemas.smartfarm import SensorReadingIn
    from app.services import smartfarm as service

    try:
        raw = json.loads(payload)
    except (TypeError, ValueError):
        logger.warning("sensor/data 페이로드가 JSON 이 아니다: %r", payload)
        return False

    try:
        reading = SensorReadingIn.model_validate(raw)
    except Exception:  # noqa: BLE001 - pydantic ValidationError 포함
        logger.warning("sensor/data 페이로드 검증 실패: %r", raw, exc_info=True)
        return False

    if reading.smartfarm_id is None:
        logger.warning("sensor/data 페이로드에 smartfarm_id 가 없다: %r", raw)
        return False

    factory = session_factory or SessionLocal
    with factory() as session:
        try:
            service.ingest_reading(
                session,
                reading.smartfarm_id,
                reading,
                received_at=datetime.now(),
            )
        except service.SmartfarmNotFound:
            logger.warning("sensor/data: 없는 smartfarm_id %s", reading.smartfarm_id)
            return False
    return True


# --------------------------------------------------------------------------
# 프로세스 단위 싱글턴 — 라우터의 startup/shutdown 훅이 여닫는다.
# --------------------------------------------------------------------------

_bridge: MqttBridge | None = None


def get_bridge() -> MqttBridge | None:
    return _bridge


def start_from_settings() -> MqttBridge | None:
    """``MQTT_BROKER_URL`` 이 설정돼 있으면 브리지를 띄운다."""
    global _bridge

    url = get_settings().mqtt_broker_url.strip()
    if not url:
        logger.info("MQTT_BROKER_URL 미설정 — 스마트팜 자동제어 브리지 비활성")
        return None
    if _bridge is not None:
        return _bridge
    try:
        bridge = MqttBridge(BrokerAddress(url))
    except Exception:  # noqa: BLE001 - 주소가 이상해도 앱은 떠야 한다
        logger.exception("MQTT_BROKER_URL 해석 실패: %r", url)
        return None
    if not bridge.start():
        return None
    _bridge = bridge
    return bridge


def stop_bridge() -> None:
    global _bridge

    bridge, _bridge = _bridge, None
    if bridge is not None:
        bridge.stop()


def publish_command(command: dict[str, Any]) -> bool:
    """브리지가 없으면 조용히 False. 자동제어 기록은 DB 에 이미 남아 있다."""
    bridge = _bridge
    if bridge is None:
        return False
    return bridge.publish_command(command)
