#!/bin/sh
# E2E 전처리 — SPEC 7.2 자동제어 경로를 실제로 한 번 태운다.
#
# 센서 시뮬레이터가 MQTT 브로커로 측정값을 흘려 넣으면 서버가 기준값과 비교해
# control/command 를 내보내고 control_events 에 기록한다. 그 기록이 남은 뒤에야
# Playwright 가 화면에서 확인할 수 있으므로, 여기서 기록을 **확인**하고 나서
# 헬스체크 표시를 남긴다 (compose 의 playwright 서비스가 이걸 기다린다).
#
# 대상은 2동 딸기 재배구역(smartfarm 2)이다. 1동 토마토(smartfarm 1)는 SPEC 5.5
# 표의 값(29.4℃ · 68% · 28%)을 그대로 들고 있어야 다른 spec 들이 성립하므로
# 건드리지 않는다.
set -eu

SMARTFARM="${SMARTFARM_ID:-2}"
API="${FARMFLOW_API_BASE_URL:-http://app:8000}"
MARKER=/tmp/sensor-scenario-done

pip install --quiet 'paho-mqtt>=2.1.0'

# 앱은 /api/health 가 뜬 뒤에 브로커에 붙는다 (connect_async + 백그라운드 루프).
# 구독 전에 발행하면 그 측정값은 그냥 사라지므로, 구독이 자리 잡을 시간을 준다.
sleep 8

python /tools/sensor_sim.py \
    --smartfarm "$SMARTFARM" \
    --scenario all \
    --transport mqtt \
    --noise 0

# 발행은 비동기다. 서버가 실제로 판단해 제어 기록을 남길 때까지 기다린다.
python - "$API" "$SMARTFARM" <<'PY'
import json
import sys
import time
import urllib.request

api, smartfarm = sys.argv[1], sys.argv[2]
url = f"{api}/api/smartfarm/{smartfarm}/controls"

for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            events = json.load(response)
        if events:
            devices = sorted({event["device"] for event in events})
            print(f"[sim] 제어 기록 {len(events)}건 — 장치 {devices}", file=sys.stderr)
            break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit(f"[sim] {url} 에 제어 기록이 끝내 생기지 않았다")
PY

touch "$MARKER"

# 여기서 종료하면 --abort-on-container-exit 가 Playwright 까지 같이 끊는다.
# 스택이 살아 있는 동안 기다린다.
exec tail -f /dev/null
