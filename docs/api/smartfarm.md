# 스마트팜 재배환경 통합관리 (SPEC 5.5 / 7.2)

라우터: `backend/app/routers/smartfarm.py` ·
서비스: `backend/app/services/smartfarm.py` ·
스키마: `backend/app/schemas/smartfarm.py`

## 엔드포인트

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/smartfarms` | 재배구역 목록 (대시보드·유휴토지 상세의 진입점) | `SmartfarmOut[]` |
| POST | `/api/smartfarm/{id}/readings` | 센서 측정값 수집. MQTT `sensor/data` 와 같은 경로로 저장하고 곧바로 자동제어를 판단한다 | `IngestResultOut` (201) |
| GET | `/api/smartfarm/{id}/status` | SPEC 5.5 표 — 측정 항목 / 적정 기준 / 현재 상태 / 자동제어 결과 + 장치 상태 | `SmartfarmStatusOut` |
| GET | `/api/smartfarm/{id}/readings?metric=&hours=` | 센서 변화 그래프용 시계열 (SPEC 4.5). `metric` 생략 시 4개 항목 전부, `hours` 기본 24 | `SensorSeriesOut` |
| GET | `/api/smartfarm/{id}/controls?limit=` | 자동제어 실행 기록 (최신순, 기본 50건) | `ControlEventOut[]` |
| POST | `/api/smartfarm/{id}/controls` | 수동 제어 — 연속 위반·히스테리시스·최소 가동시간을 우회한다 | `ControlEventOut` (201) |

`metric` 은 `temp_c` · `humidity_pct` · `soil_moisture_pct` · `lux` 중 하나이며,
그 밖의 값은 422 다. 시계열 구간의 기준 시각은 벽시계가 아니라 **마지막 측정값의
`ts`** 라서 시드 데이터(ANCHOR_DATE)로도 그래프가 비지 않는다.

```jsonc
// SensorReadingIn — POST /api/smartfarm/{id}/readings 본문
// ts 를 생략하면 수신 시각을 쓴다. 시뮬레이터와 테스트는 항상 지정한다.
{ "ts": "2026-08-08T14:00:00", "temp_c": 29.4, "humidity_pct": 68.0,
  "lux": 12300, "soil_moisture_pct": 28.0 }

// IngestResultOut — 저장된 측정값 + 그 결과로 나간 명령
{ "reading": { "id": 1, "smartfarm_id": 1, "ts": "2026-08-08T14:00:00", ... },
  "controls": [ /* ControlEventOut */ ] }

// ControlEventOut
{ "id": 12, "smartfarm_id": 1, "ts": "2026-08-08T14:00:00", "device": "fan",
  "action": "on", "reason": "온도 29.4℃ — 적정 상한 27.0℃ 초과, 환기 가동",
  "metric": "temp_c", "value_before": 29.4, "value_after": 26.5 }

// SmartfarmStatusOut — metrics 행이 SPEC 5.5 표의 한 줄이다
{ "smartfarm_id": 1, "name": "1동 토마토 재배구역", "crop": "토마토",
  "type": "비닐하우스", "ts": "2026-08-08T14:00:00",
  "metrics": [
    { "metric": "temp_c", "label": "온도", "unit": "℃", "value": 29.4,
      "display": "29.4℃", "target_min": 22.0, "target_max": 27.0,
      "target_display": "22~27℃", "in_range": false,
      "device": "fan", "device_action": "on", "control_display": "환기 후 26.5℃" }
  ],
  "devices": [ { "device": "fan", "action": "on", "since": "...", "reason": "..." } ] }

// ManualControlIn — POST /api/smartfarm/{id}/controls 본문
{ "device": "pump", "action": "on", "reason": "농가 수동 급수" }
```

`device` 는 `pump` · `fan` · `light`, `action` 은 `on` · `off` 다.
조도는 절대값이 아니라 기준 대비 백분율로 표시한다 (`"기준의 82%"`).
