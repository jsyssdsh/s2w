#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["paho-mqtt>=2.1.0"]
# ///
"""센서 시뮬레이터 — 실물 ESP32 없이 스마트팜 자동제어를 돌린다 (SPEC 6 / 7.2).

시드된 스마트팜에 현실적인 센서 스트림을 흘려 넣는다. 평상시 프로파일 하나와,
서버의 제어 경로를 하나씩 태우는 시나리오 셋이 있다:

===============  ==========================================================
시나리오          거치는 제어 경로
===============  ==========================================================
``normal``        아무 명령도 나오지 않는다 (정상 상태 유지)
``heat_spike``    온도 상한 초과 → **환기** 가동 → 회복 → 정지
``soil_dry_down`` 토양수분 하한 미만 → **급수** 가동 → 회복 → 정지
``dusk``          조도 기준 미만 → **조명** 가동 → 회복 → 정지
``all``           위 넷을 순서대로 이어 붙인다
===============  ==========================================================

기본 시나리오 값은 SPEC 5.5 워크드 예제 그대로다 — 29.4℃ → 환기 후 26.5℃,
토양수분 28% → 급수 후 41%, 조도 기준의 82% → 조명 후 101%.

판단은 전부 서버가 한다 (docs/ARCHITECTURE.md 11절). 이 시뮬레이터는 ESP32 의
**센서 쪽**만 흉내낸다 — 측정값을 만들어 ``sensor/data`` 로 발행할 뿐,
기준값을 스스로 판단하지 않는다. 기준값은 실행 시 서버의
``GET /api/smartfarm/{id}/status`` 에서 읽어 오고, 서버에 닿지 못하면 토마토
기본값으로 떨어진다.

**결정론**: 같은 ``--seed`` 는 항상 같은 스트림을 만든다. ``--noise 0`` 이면
잡음이 완전히 빠져 SPEC 표의 숫자가 소수점까지 그대로 나온다.

사용 예::

    # 브로커로 발행 (docker compose up 으로 브로커 + 앱이 떠 있을 때)
    uv run tools/sensor_sim.py --smartfarm 1 --scenario heat_spike

    # 브로커 없이 REST 로 직접 수집 경로를 태운다
    uv run tools/sensor_sim.py --smartfarm 1 --scenario all --transport rest

    # 발행하지 않고 만들어질 값만 본다
    uv run tools/sensor_sim.py --scenario dusk --transport print

의존성이 필요한 것은 ``--transport mqtt`` 뿐이다 (paho-mqtt). ``rest`` 와
``print`` 는 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

# docs/ARCHITECTURE.md 11.1 — 토픽 계약. 서버와 문자열이 같아야 한다.
SENSOR_TOPIC = "sensor/data"

DEFAULT_BROKER = "mqtt://localhost:1883"
DEFAULT_API_BASE = "http://localhost:8000"

#: ANCHOR_DATE(2026-08-08) 다음 날 09:00. 시드 데이터의 마지막 측정값보다 뒤라
#: 시뮬레이션이 기존 시계열에 자연스럽게 이어 붙는다.
DEFAULT_START = datetime(2026, 8, 9, 9, 0)

DEFAULT_SEED = 20260808
DEFAULT_INTERVAL_MIN = 10
DEFAULT_NOISE = 0.1
DEFAULT_RATE = 2.0


@dataclass(frozen=True)
class Thresholds:
    """작물별 적정 생육 기준 (``crop_thresholds`` 한 행).

    기본값은 SPEC 5.5 의 토마토 기준이다. 서버에 닿을 수 있으면
    :func:`fetch_thresholds` 가 실제 값으로 갈아끼운다.
    """

    temp_min: float = 22.0
    temp_max: float = 27.0
    humidity_min: float = 60.0
    humidity_max: float = 75.0
    soil_moisture_min: float = 35.0
    soil_moisture_max: float = 55.0
    lux_min: float = 15000.0

    @property
    def temp_mid(self) -> float:
        return (self.temp_min + self.temp_max) / 2

    @property
    def humidity_mid(self) -> float:
        return (self.humidity_min + self.humidity_max) / 2

    @property
    def soil_mid(self) -> float:
        return (self.soil_moisture_min + self.soil_moisture_max) / 2


# --------------------------------------------------------------------------
# 프로파일 — 한 시나리오는 (측정값 개수, 목표값) 구간의 나열이다.
#
# 목표값은 서버의 판단 규칙(연속 3회 위반 · 히스테리시스 여유분 · 최소 가동시간
# 10분)을 넉넉히 넘기도록 잡았다. 기본 잡음 ±0.1 로는 판단이 뒤집히지 않는다.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Segment:
    """연속한 ``count`` 개 측정값이 향하는 목표. ``None`` 은 평상시 값."""

    count: int
    temp_c: float | None = None
    humidity_pct: float | None = None
    lux_factor: float | None = None  # lux_min 대비 배율
    soil_moisture_pct: float | None = None
    label: str = ""


#: 평상시 — 네 항목 모두 적정 범위 한가운데. 낮 시간대라 조도도 기준 이상이다.
_NORMAL = (_Segment(count=12, label="평상시"),)

#: 고온 → 환기. 27℃ 상한을 3회 연속 넘겨 가동시키고, 26.3℃ 로 내려 정지시킨다
#: (정지 기준은 상한 − 0.5℃ = 26.5℃).
_HEAT_SPIKE = (
    _Segment(count=3, label="평상시"),
    _Segment(count=1, temp_c=27.6, label="상승"),
    _Segment(count=1, temp_c=28.5, label="상승"),
    _Segment(count=1, temp_c=29.4, label="상한 초과 3회째 → 환기 가동"),
    _Segment(count=3, temp_c=29.4, label="고온 지속"),
    _Segment(count=2, temp_c=26.3, label="환기 후 회복 → 환기 정지"),
)

#: 토양 건조 → 급수. 35% 하한을 3회 연속 밑돌아 가동, 41% 로 회복해 정지
#: (정지 기준은 하한 + 5%p = 40%).
_SOIL_DRY_DOWN = (
    _Segment(count=3, label="평상시"),
    _Segment(count=1, soil_moisture_pct=38.0, label="건조 시작 (아직 적정)"),
    _Segment(count=1, soil_moisture_pct=34.0, label="하한 미만"),
    _Segment(count=1, soil_moisture_pct=31.0, label="하한 미만"),
    _Segment(count=1, soil_moisture_pct=28.0, label="하한 미만 3회째 → 급수 가동"),
    _Segment(count=2, soil_moisture_pct=28.0, label="급수 대기"),
    _Segment(count=2, soil_moisture_pct=41.0, label="급수 후 회복 → 급수 정지"),
)

#: 해질녘 → 조명. 조도가 기준 아래로 3회 연속 떨어져 가동, 기준의 101% 로
#: 회복해 소등한다. 온도도 함께 내려가지만 적정 범위 안에 머문다.
_DUSK = (
    _Segment(count=3, label="한낮"),
    _Segment(count=1, lux_factor=0.95, temp_c=24.0, label="일몰 시작"),
    _Segment(count=1, lux_factor=0.88, temp_c=23.6, label="기준 미만"),
    _Segment(count=1, lux_factor=0.82, temp_c=23.2, label="기준 미만 3회째 → 조명 가동"),
    _Segment(count=3, lux_factor=0.82, temp_c=23.0, label="보광 중"),
    _Segment(count=2, lux_factor=1.01, temp_c=23.0, label="기준 충족 → 소등"),
)

SCENARIOS: dict[str, tuple[_Segment, ...]] = {
    "normal": _NORMAL,
    "heat_spike": _HEAT_SPIKE,
    "soil_dry_down": _SOIL_DRY_DOWN,
    "dusk": _DUSK,
    "all": _NORMAL + _HEAT_SPIKE + _SOIL_DRY_DOWN + _DUSK,
}


def _daylight(index: int, period: int = 24) -> float:
    """0..1 사이를 완만하게 오가는 낮 곡선. 평상시 값에 살짝 흔들림을 준다."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * index / period)


def generate(
    scenario: str,
    *,
    smartfarm_id: int = 1,
    thresholds: Thresholds | None = None,
    seed: int = DEFAULT_SEED,
    start: datetime | None = None,
    interval_min: int = DEFAULT_INTERVAL_MIN,
    noise: float = DEFAULT_NOISE,
    count: int | None = None,
) -> list[dict]:
    """시나리오 하나를 ``sensor/data`` 페이로드 목록으로 펼친다.

    반환값의 각 항목은 서버의 ``SensorReadingIn`` 과 필드가 정확히 같다
    (docs/ARCHITECTURE.md 11.1). ``count`` 를 주면 그 개수로 자르거나
    마지막 구간을 반복해 늘린다.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"모르는 시나리오: {scenario} (가능: {', '.join(SCENARIOS)})")

    limits = thresholds or Thresholds()
    rng = random.Random(seed)
    at = start or DEFAULT_START
    step = timedelta(minutes=interval_min)

    segments = list(SCENARIOS[scenario])
    if count is not None:
        segments = _resize(segments, count)

    readings: list[dict] = []
    index = 0
    for segment in segments:
        for _ in range(segment.count):
            readings.append(
                _reading(smartfarm_id, at, index, segment, limits, rng, noise)
            )
            at += step
            index += 1
    return readings


def _resize(segments: list[_Segment], count: int) -> list[_Segment]:
    """구간 나열을 정확히 ``count`` 개 측정값으로 맞춘다."""
    total = sum(s.count for s in segments)
    if count <= 0:
        return []
    if count == total:
        return segments
    if count < total:
        trimmed: list[_Segment] = []
        left = count
        for segment in segments:
            if left <= 0:
                break
            take = min(left, segment.count)
            trimmed.append(replace(segment, count=take))
            left -= take
        return trimmed
    last = segments[-1]
    return segments[:-1] + [replace(last, count=last.count + count - total)]


def _reading(
    smartfarm_id: int,
    ts: datetime,
    index: int,
    segment: _Segment,
    limits: Thresholds,
    rng: random.Random,
    noise: float,
) -> dict:
    """구간의 목표값 + 평상시 기본값 + 잡음 → 측정값 한 건."""
    sway = _daylight(index)

    temp = segment.temp_c
    if temp is None:
        temp = limits.temp_mid + 1.2 * sway
    humidity = segment.humidity_pct
    if humidity is None:
        humidity = limits.humidity_mid - 2.5 * sway
    soil = segment.soil_moisture_pct
    if soil is None:
        soil = limits.soil_mid - 1.5 * sway
    lux_factor = segment.lux_factor
    if lux_factor is None:
        lux_factor = 1.15 + 0.25 * sway

    return {
        "smartfarm_id": smartfarm_id,
        "ts": ts.isoformat(),
        "temp_c": _jitter(rng, temp, noise, 1),
        "humidity_pct": _jitter(rng, humidity, noise, 1),
        "lux": _jitter(rng, limits.lux_min * lux_factor, noise * limits.lux_min / 100, 0),
        "soil_moisture_pct": _jitter(rng, soil, noise, 1),
    }


def _jitter(rng: random.Random, value: float, noise: float, digits: int) -> float:
    """±noise 안의 균등 잡음. ``noise=0`` 이면 값이 그대로 나온다."""
    if noise:
        value += rng.uniform(-noise, noise)
    rounded = round(value, digits)
    return rounded if digits else float(rounded)


# --------------------------------------------------------------------------
# 전송
# --------------------------------------------------------------------------


def fetch_thresholds(api_base: str, smartfarm_id: int) -> Thresholds | None:
    """``GET /api/smartfarm/{id}/status`` 의 적정 기준을 읽어 온다.

    서버에 닿지 못하면 ``None`` — 호출자가 토마토 기본값으로 떨어진다.
    """
    url = f"{api_base.rstrip('/')}/api/smartfarm/{smartfarm_id}/status"
    try:
        with urlrequest.urlopen(url, timeout=5) as response:
            body = json.loads(response.read())
    except (urlerror.URLError, OSError, ValueError, TimeoutError):
        return None

    rows = {row["metric"]: row for row in body.get("metrics", [])}
    if not rows:
        return None
    defaults = Thresholds()

    def bound(metric: str, key: str, fallback: float) -> float:
        value = rows.get(metric, {}).get(key)
        return float(value) if value is not None else fallback

    return Thresholds(
        temp_min=bound("temp_c", "target_min", defaults.temp_min),
        temp_max=bound("temp_c", "target_max", defaults.temp_max),
        humidity_min=bound("humidity_pct", "target_min", defaults.humidity_min),
        humidity_max=bound("humidity_pct", "target_max", defaults.humidity_max),
        soil_moisture_min=bound(
            "soil_moisture_pct", "target_min", defaults.soil_moisture_min
        ),
        soil_moisture_max=bound(
            "soil_moisture_pct", "target_max", defaults.soil_moisture_max
        ),
        lux_min=bound("lux", "target_min", defaults.lux_min),
    )


class MissingPaho(RuntimeError):
    """paho-mqtt 가 없다. mqtt 전송에만 필요하다."""


class MqttPublisher:
    """``sensor/data`` 로 발행한다 — ESP32 가 하는 일 그대로."""

    def __init__(self, broker_url: str) -> None:
        try:
            from paho.mqtt.client import CallbackAPIVersion, Client
        except ImportError as exc:  # noqa: PERF203 - 안내가 스택트레이스보다 낫다
            raise MissingPaho(
                "paho-mqtt 가 없다. 다음 중 하나로 실행한다:\n"
                "  uv run tools/sensor_sim.py ...          (인라인 의존성으로 자동 설치)\n"
                "  uv run --with paho-mqtt python tools/sensor_sim.py ...\n"
                "  tools/sensor_sim.py ... --transport rest  (브로커 없이 REST 로)"
            ) from exc

        parsed = urlparse(broker_url if "//" in broker_url else f"mqtt://{broker_url}")
        tls = (parsed.scheme or "mqtt").lower() in ("mqtts", "ssl", "mqtt+ssl")
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or (8883 if tls else 1883)

        self._client = Client(CallbackAPIVersion.VERSION2, client_id="farmflow-sensor-sim")
        if parsed.username:
            self._client.username_pw_set(parsed.username, parsed.password)
        if tls:
            self._client.tls_set()

    def __enter__(self) -> MqttPublisher:
        self._client.connect(self.host, self.port)
        self._client.loop_start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def send(self, payload: dict) -> None:
        # 서버 브리지가 qos=1 로 구독한다. 발행도 맞춰야 한 건도 흘리지 않는다.
        info = self._client.publish(
            SENSOR_TOPIC, json.dumps(payload, ensure_ascii=False), qos=1
        )
        info.wait_for_publish(timeout=10)


class RestPublisher:
    """브로커 없이 ``POST /api/smartfarm/{id}/readings`` 로 같은 값을 넣는다.

    서버의 REST 핸들러와 MQTT 구독자는 같은 ``ingest_reading()`` 을 부르므로
    자동제어 결과가 동일하다 (docs/ARCHITECTURE.md 11.1).
    """

    def __init__(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")

    def __enter__(self) -> RestPublisher:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def send(self, payload: dict) -> None:
        smartfarm_id = payload["smartfarm_id"]
        body = json.dumps(payload, ensure_ascii=False).encode()
        request = urlrequest.Request(
            f"{self.api_base}/api/smartfarm/{smartfarm_id}/readings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(request, timeout=10) as response:
            response.read()


class PrintPublisher:
    """아무 데도 보내지 않고 JSON 한 줄씩 찍는다 (dry-run)."""

    def __enter__(self) -> PrintPublisher:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def send(self, payload: dict) -> None:
        print(json.dumps(payload, ensure_ascii=False))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensor_sim.py",
        description="스마트팜 센서 시뮬레이터 (SPEC 6 / 7.2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="예: uv run tools/sensor_sim.py --smartfarm 1 --scenario heat_spike",
    )
    parser.add_argument("--smartfarm", type=int, default=1, help="대상 스마트팜 id (기본 1)")
    parser.add_argument(
        "--scenario",
        default="normal",
        choices=sorted(SCENARIOS),
        help="시나리오 (기본 normal)",
    )
    parser.add_argument(
        "--transport",
        default="mqtt",
        choices=("mqtt", "rest", "print"),
        help="mqtt: 브로커로 발행 · rest: API 로 직접 · print: 출력만 (기본 mqtt)",
    )
    parser.add_argument("--broker", default=None, help=f"브로커 URL (기본 $MQTT_BROKER_URL 또는 {DEFAULT_BROKER})")
    parser.add_argument(
        "--api-base",
        default=None,
        help=f"API 주소 (기본 $FARMFLOW_API_BASE_URL 또는 {DEFAULT_API_BASE})",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="난수 시드 — 같으면 같은 스트림")
    parser.add_argument(
        "--rate",
        type=float,
        default=DEFAULT_RATE,
        help="초당 발행 건수. 0 이면 대기 없이 최대 속도 (기본 2)",
    )
    parser.add_argument(
        "--interval-min",
        type=int,
        default=DEFAULT_INTERVAL_MIN,
        help="측정값 사이의 **가상** 시간 간격(분). 서버 판단은 이 ts 를 본다 (기본 10)",
    )
    parser.add_argument("--count", type=int, default=None, help="측정값 개수 강제 지정")
    parser.add_argument(
        "--noise",
        type=float,
        default=DEFAULT_NOISE,
        help="잡음 크기. 0 이면 SPEC 표의 숫자가 그대로 나온다 (기본 0.1)",
    )
    parser.add_argument(
        "--start",
        default=None,
        help=f"첫 측정값의 ts (ISO 8601, 기본 {DEFAULT_START.isoformat()})",
    )
    parser.add_argument(
        "--no-fetch-thresholds",
        action="store_true",
        help="서버에서 적정 기준을 읽지 않고 토마토 기본값을 쓴다",
    )
    return parser


def _publisher(args: argparse.Namespace, broker: str, api_base: str):
    if args.transport == "print":
        return PrintPublisher()
    if args.transport == "rest":
        return RestPublisher(api_base)
    return MqttPublisher(broker)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    broker = args.broker or os.environ.get("MQTT_BROKER_URL") or DEFAULT_BROKER
    api_base = args.api_base or os.environ.get("FARMFLOW_API_BASE_URL") or DEFAULT_API_BASE

    thresholds = None
    if not args.no_fetch_thresholds:
        thresholds = fetch_thresholds(api_base, args.smartfarm)
        if thresholds is None:
            print(
                f"[sim] {api_base} 에서 적정 기준을 못 읽었다 — 토마토 기본값을 쓴다",
                file=sys.stderr,
            )

    readings = generate(
        args.scenario,
        smartfarm_id=args.smartfarm,
        thresholds=thresholds,
        seed=args.seed,
        start=datetime.fromisoformat(args.start) if args.start else None,
        interval_min=args.interval_min,
        noise=args.noise,
        count=args.count,
    )

    delay = 1.0 / args.rate if args.rate > 0 else 0.0
    print(
        f"[sim] smartfarm={args.smartfarm} scenario={args.scenario} "
        f"transport={args.transport} readings={len(readings)}",
        file=sys.stderr,
    )

    try:
        with _publisher(args, broker, api_base) as publisher:
            for i, payload in enumerate(readings):
                publisher.send(payload)
                if delay and i < len(readings) - 1:
                    time.sleep(delay)
    except KeyboardInterrupt:
        print("[sim] 중단됨", file=sys.stderr)
        return 130
    except MissingPaho as exc:
        print(f"[sim] {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        target = broker if args.transport == "mqtt" else api_base
        print(f"[sim] 전송 실패 ({target}): {exc}", file=sys.stderr)
        return 1

    print(f"[sim] 완료 — {len(readings)}건 전송", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
