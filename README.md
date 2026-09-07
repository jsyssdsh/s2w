# 울퉁불퉁 농장 AI (FarmFlow AI)

> 휴경농지·스마트팜·농산물 유통 데이터를 하나로 묶어, AI가 시세를 예측하고
> 최적의 도매처·판매처·농지를 추천해주는 **생산-유통 통합 플랫폼**

충남 지역의 휴경농지 증가(2024년 1만 1,135ha, 휴경률 5.2%)와 신규 농업인의
판로 확보 문제를 함께 풀기 위한 프로토타입이다. 유휴농지를 신규 농업인과
연결하고, 그 위에 조성한 스마트팜의 생육환경을 자동으로 관리하며, 생산된
농산물을 가장 수익성 높은 거래처로 이어준다.

전체 기획은 [SPEC.md](./SPEC.md), 개발 규약은
[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md), 엔드포인트 목록은
[docs/API.md](./docs/API.md) 를 참고한다.

**처음 보는 사람은 [docs/DEMO.md](./docs/DEMO.md) 부터 읽으면 된다** — 화면을
순서대로 짚는 시연 대본과, SPEC 각 절이 어디에 구현됐고 무엇이 그것을 증명하는지
적은 검증표가 들어 있다.

## 주요 기능

| 기능 | 내용 | SPEC |
|---|---|---|
| AI 시세 예측 | 과거 가격·거래량·기상 데이터로 출하일별 예상 가격을 비교 | 5.1 |
| 도매처 추천 | 매입단가·구매량·운송비·수수료로 예상 순수익을 계산해 순위화 | 5.2 |
| 판매처 연계 | 등급·판매기한·재고를 보고 마트/급식/가공/음식점에 연결 | 5.3 |
| 수급 위험 알림 | 지역 출하량 대비 수요를 비교해 초과 물량과 대응 방안을 제시 | 5.4 |
| 스마트팜 자동제어 | 센서값이 적정 범위를 벗어나면 펌프·환기팬·조명을 MQTT 로 제어 | 5.5 / 7.2 |
| ESP32 엣지 제어기 | 센서 측정·발행, 릴레이 구동, 연결이 끊기면 제한적 안전 제어 | 6.2 / 7.2 |
| 유휴농지 매칭 | 희망 작물·면적·예산과 용수·냉장창고·거리 조건을 비교해 농지를 추천 | 5.6 / 7.3 |

## 구조 (SPEC 6.1 데이터 흐름)

```
[1. 데이터 수집]
  공공데이터 (시드 데이터로 대체) ─┐
  플랫폼 사용자 입력 (React 화면) ─┼─▶ [2. 소프트웨어]
  IoT 센서 데이터 (ESP32/시뮬레이터)┘
                                      FastAPI 서버
                                        → 데이터 전처리 (서비스 계층 · NumPy)
                                        → 통합 데이터베이스 (SQLite · SQLAlchemy 2.0)
                                        → AI 의사결정 엔진
                                             · 가격 예측   (scikit-learn HistGradientBoosting)
                                             · 유통 추천   (순수익 점수화 + 거래 이행률)
                                             · 수급위험 분석
                                             · 휴경농지 추천 (6축 가중합)
                                        → 앱 대시보드 (Next.js 정적 내보내기, 같은 포트로 서빙)

[3. 하드웨어 · 자동제어]
  스마트팜 센서 → ESP32 엣지 제어기 ──MQTT(sensor/data)──▶ 서버 판단
  서버 판단 ──MQTT(control/command)──▶ ESP32 → 릴레이 → 펌프 / 환기팬 / 조명
```

디렉터리:

```
backend/    FastAPI + SQLAlchemy 2.0 + SQLite (uv 로 관리)
frontend/   Next.js App Router + TypeScript + Tailwind (정적 내보내기)
firmware/   ESP32 엣지 제어기 (PlatformIO · C++)
mosquitto/  MQTT 브로커 설정
tools/      센서 시뮬레이터
test/       Playwright E2E
scripts/    macOS · Windows 실행 스크립트
docs/       시연 대본 · 검증표 · 아키텍처 규약 · API 레퍼런스
```

빌드하면 프론트엔드가 정적 파일로 내보내져 FastAPI 가 API 와 함께
**단일 컨테이너 · 단일 포트(8000)** 로 서빙한다. 여기에 MQTT 브로커
컨테이너 하나가 붙어 스마트팜 자동제어(SPEC 7.2)를 담당한다.

### 프로토타입 편차 — SQLite vs PostgreSQL/PostGIS

SPEC 6.2 는 **PostgreSQL + PostGIS** 를 적었지만 이 프로토타입은 **SQLite** 를 쓴다.
심사자가 클론 한 번으로 아무 설치 없이 돌릴 수 있어야 하기 때문이다. 옮겨 갈 자리는
두 곳으로 좁혀 두었다:

- **스키마**: enum 컬럼을 네이티브 enum 이 아니라 `VARCHAR + CHECK` 로 잡아서
  PostgreSQL 로 그대로 옮겨 간다 (`backend/app/models.py`).
- **공간 질의**: 거리 계산이 전부 `app/services/geo.haversine_km` 한 함수를 지나간다.
  PostGIS 로 바꿀 때 갈아 끼울 지점이 여기 하나다.

그 밖의 편차(공공데이터 API → 결정론적 시드, 실물 ESP32 → 시뮬레이터, 로그인 없음)는
[docs/DEMO.md 2.6](./docs/DEMO.md) 에 표로 정리해 두었다.

## 실행

필요한 것은 **Docker 하나뿐**이다. `.env` 는 없어도 된다 — 없으면
`.env.example` 과 같은 기본값으로 뜬다.

### 도커 컴포즈 (권장 · macOS · Windows 공통)

```bash
docker compose up --build
# http://localhost:8000        웹 + API
# mqtt://localhost:1883        Mosquitto 브로커 (SPEC 7.2)
```

멈출 때는 `docker compose down`, 데이터까지 지우려면 `docker compose down -v`.

### 스크립트 (브로커 없이 앱만)

MQTT 브로커 없이 웹과 API 만 띄우고 브라우저까지 열어 준다.

**macOS · Linux**

```bash
./scripts/start_mac.sh --build   # 첫 실행 (이후에는 --build 생략 가능)
./scripts/stop_mac.sh
```

**Windows (PowerShell)**

```powershell
.\scripts\start_windows.ps1 --build
.\scripts\stop_windows.ps1
```

두 스크립트 모두 멱등이다 — 여러 번 돌려도 컨테이너가 하나만 남는다.
`.env` 가 있으면 읽고, 없으면 그냥 기본값으로 뜬다.

### 환경변수

전부 선택 사항이다. 바꾸려면 `cp .env.example .env` 후 편집한다.

| 변수 | 기본값 | 용도 |
|---|---|---|
| `DB_PATH` | `/app/db/farmflow.db` | SQLite 파일 경로 (컨테이너는 `farmflow-data` 볼륨에 저장) |
| `MQTT_BROKER_URL` | 컴포즈에서 `mqtt://mosquitto:1883`, 그 밖에는 비어 있음 | 스마트팜 자동제어 브로커 (SPEC 7.2). 비우면 REST 전용 모드 |
| `SEED_ON_START` | `true` | 빈 DB 를 시작 시 시드 데이터로 채운다 |
| `LLM_MOCK` | `false` | 결정론적 목 응답 (테스트·데모용) |
| `STATIC_DIR` | `/app/static` | 내보내진 프론트엔드 위치 |

### 로컬 개발

백엔드:

```bash
cd backend
uv sync
DB_PATH=./db/farmflow.db uv run uvicorn app.main:app --reload
# API      http://localhost:8000/api/health
# Swagger  http://localhost:8000/docs
```

프론트엔드 (별도 개발 서버):

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
# http://localhost:3000
```

## 시드 데이터

시드는 **결정론적**이다 — 고정 RNG 시드와 고정 기준일(`ANCHOR_DATE`,
2026-08-08)을 쓰므로 매번 같은 숫자가 나온다. SPEC 5장의 예제
(토마토 2,450원/kg, 도매처 A/B/C, 양파 초과공급 28톤, 농지 A/B/C 등)를 그대로
재현하므로 데모와 테스트가 같은 데이터를 본다.

빈 DB 로 앱을 시작하면 자동으로 채워진다(`SEED_ON_START=true`). 수동 실행:

```bash
cd backend && uv run python -m app.seed
```

## 스마트팜 (SPEC 6 / 7.2)

ESP32 가 온습도·조도·토양수분을 읽어 `sensor/data` 로 올리면, 서버가 작물별
기준값과 비교해 `control/command` 로 워터펌프·환기팬·조명을 제어한다.
연결이 끊기면 ESP32 가 보수적인 안전 기준으로 제한 제어를 이어간다.

- 펌웨어와 배선표: [firmware/README.md](./firmware/README.md)
- 토픽·페이로드 계약: [docs/ARCHITECTURE.md 11절](./docs/ARCHITECTURE.md)

실물 보드가 없어도 전체 흐름을 돌려볼 수 있다:

```bash
docker compose up --build                                            # 브로커 + 앱
docker compose exec mosquitto mosquitto_sub -t 'control/command' -v  # 명령 구독 (창 하나)
docker compose --profile sim run --rm sensor-sim --smartfarm 1 --scenario heat_spike
```

시나리오는 `normal` / `heat_spike` / `soil_dry_down` / `dusk` / `all` 이며,
같은 `--seed` 는 항상 같은 스트림을 만든다. 파이썬이 이미 있다면 컨테이너 없이
`uv run tools/sensor_sim.py --smartfarm 1 --scenario heat_spike` 로 같은 일을 한다
(브로커 없이 REST 로만 태우려면 `--transport rest`).

## 테스트

```bash
# 백엔드 단위/통합 테스트 (시뮬레이터 → 자동제어 통합 테스트 포함)
cd backend && uv run pytest

# 프론트엔드 타입·린트
cd frontend && npm ci && npm run typecheck && npm run lint

# 펌웨어 오프라인 안전 규칙 (보드 없이)
./firmware/run_host_tests.sh

# 컨테이너 전체 E2E — 브로커 + 앱 + 센서 시뮬레이터 + Playwright
docker compose -f docker-compose.test.yml up --build --exit-code-from playwright
```

E2E 스택은 SPEC 7 의 세 운영 시나리오를 **끝에서 끝까지** 돌린다. 특히 7.2 는
Mosquitto 를 실제로 띄우고 `tools/sensor_sim.py` 로 `sensor/data` 를 발행해
서버가 남긴 제어 기록이 화면에 도달하는지까지 확인한다 (REST 로 우회하지 않는다).
어떤 SPEC 절을 어떤 테스트가 증명하는지는 [docs/DEMO.md 2부](./docs/DEMO.md) 의
검증표에 있다.
