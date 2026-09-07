# 데모 대본 및 검증 보고서 (SPEC 2.3)

> 이 문서는 **SPEC 2.3 "최종 결과 및 검증 목표"** 의 산출물이다.
> 1부는 화면을 순서대로 짚는 시연 대본이고, 2부는 SPEC 각 절이 실제로 어디에
> 구현됐고 무엇이 그것을 증명하는지 적은 검증표다.
>
> 대본에 적힌 숫자는 전부 **시드 데이터가 보장하는 값**이다. 시드는 고정 RNG
> 시드와 고정 기준일(`ANCHOR_DATE = 2026-08-08`)을 쓰므로, 같은 화면을 몇 번
> 열어도 같은 숫자가 나온다. 다르게 나온다면 그건 버그다.

---

## 0. 준비

```bash
git clone <repo> && cd s2w
docker compose up --build
# http://localhost:8000        웹 + API
# mqtt://localhost:1883        Mosquitto 브로커 (SPEC 7.2)
```

`.env` 는 없어도 된다 — 없으면 `.env.example` 의 기본값과 같게 뜬다. 첫 기동은
컨테이너 안에서 의존성을 동기화하므로 `docker compose up` 이 돌아온 뒤에도 몇 초
더 걸린다. `http://localhost:8000/api/health` 가 `{"status":"ok"}` 를 주면 준비된 것이다.

브라우저는 `http://localhost:8000` 하나만 열면 된다. 프론트엔드는 정적으로
내보내져 FastAPI 가 API 와 같은 포트로 서빙한다.

---

## 1부 · 시연 대본

각 단계의 **기대값**은 SPEC 표의 숫자다. 화면에서 눈으로 확인할 것을 적었다.

### 1. 홈 화면 (SPEC 4.1) — `/`

1. 메뉴 카드 세 개가 보인다: **농가 대시보드 / 유통업체 대시보드 / 유휴토지 지도**.
2. 그 아래 **연결 과정 시각화**에 `유휴농지 → 농가 → 유통업체` 가 한 줄로 놓인다.
3. 오른쪽 **사용자 유형 메뉴**에서 유형을 `유통업체` 로 바꾸면 메뉴가 유통업체용으로 갈아 끼워진다.

> SPEC 4.1 "향후 수정 계획"(연결 과정 시각화 + 유형별 맞춤 메뉴)까지 이미 화면에 있다.

### 2. 농가 대시보드 (SPEC 4.2) — `/farm/`

**메인 현황 카드** — SPEC 4.2 가 요구하는 다섯 값:

| 항목 | 기대값 | 근거 |
|---|---|---|
| 현재 작물 | 토마토 (1동 토마토 재배구역) | 시드 |
| 예상 수확량 | **1,000kg** | 시드 |
| 현재 도매가 | **2,450원/kg** | SPEC 5.1 표의 8월 8일 값 |
| AI 추천 유통처 | **B 농산물유통** | SPEC 5.2 순위 1위 |
| 예상 수익률 | 순수익 ÷ 판매금액 | SPEC 5.2 계산식 |

**스마트팜 상태** — SPEC 5.5 표가 그대로 한 줄씩:

| 측정 항목 | 적정 기준 | 현재 상태 | 자동제어 결과 |
|---|---|---|---|
| 온도 | 22~27℃ | **29.4℃** (범위 이탈) | 환기 후 26.5℃ |
| 습도 | 60~75% | 68% (적정) | 정상 상태 유지 |
| 토양수분 | 35~55% | **28%** (범위 이탈) | 급수 후 41% |
| 조도 | 기준 이상 | **기준의 82%** | 조명 후 101% |

**AI 분석 알림** — "시장 가격 상승/하락 가능성 안내" 와 센서 범위 이탈 항목이 뜬다.

**빠른 기능 탭 네 개**를 차례로 누른다:

1. **작물 등록** — 토마토 / 1000 / 2026-08-08 / 특상품 을 넣고 등록한다.
2. **AI 유통 추천** — 등록 즉시 SPEC 5.2 비교표가 뜬다:

   | 순위 | 도매처 | 매입단가 | 구매량 | 운송비 | 예상 순수익 |
   |---|---|---|---|---|---|
   | 1위 | B 농산물유통 | 2,580원/kg | 1,000kg | 80,000원 | **2,422,600원** |
   | 2위 | A 청과도매 | 2,550원/kg | 1,000kg | 180,000원 | **2,293,500원** |
   | 3위 | C 도매시장 | 2,700원/kg | 800kg | 210,000원 | **1,885,200원** |

   > SPEC 5.2 표는 A 를 239만 5,000원으로 적었지만 같은 행의 단가·구매량·운송비로는
   > 그 값이 나올 수 없다(수수료 0 으로 놓아도 237만원이 상한). 수수료 3% 를 반영한
   > 실제 값이 **229만 3,500원**이고 B·C 는 SPEC 과 정확히 일치한다. SPEC 이 요구하는
   > 결론인 **순위 B > A > C** 는 그대로다. 근거: `docs/api/wholesaler_rec.md`.

3. **가격 분석** — 시세 변화 그래프(실적 + 예측)와 SPEC 5.1 출하일 비교표:

   | 비교항목 | 8월 8일 | 8월 10일 | 8월 17일 |
   |---|---|---|---|
   | 예상 도매가격 | 2,450원/kg | (예측) | (예측) |
   | 예상 판매금액 | 245만 원 | | |
   | 시스템 안내 | 즉시 출하 가능 / 출하 유지 권장 / 조기 출하 검토 중 하나 | | |

4. **거래 현황** — 아래 5번에서 채워진다.

5. 추천표 1위 줄의 **"이 도매처 선택"** 을 누른다 → **거래 현황** 에
   `B 농산물유통 · 거래 수락 · 토마토 1,000kg` 이 남는다. 같은 출하의 나머지
   제안은 자동으로 닫힌다.
6. 다시 **AI 유통 추천** 을 눌러 보면 A·C 의 **이행률(reliability)** 이 내려가 있다.
   순수익 숫자는 그대로고 **정렬 기준값만** 깎인다 — SPEC 7.1 의 "실제 거래 결과는
   다음 추천에 반영한다" 가 이것이다.

### 3. 유통업체 대시보드 (SPEC 4.3) — `/distributor/`

**요약 타일**: 공급 가능 건수 / AI 추천 건수 / 예상 금액.

**AI 추천 농가 리스트** — SPEC 4.3 "향후 수정 계획"의 열까지 다 있다:
농가 · 출하일 · 품질 등급 · 공급량 · **거리** · **운송비** · **권장 거래가** ·
**예상 순수익** · **추천 이유**. 열 제목을 누르면 다시 정렬된다 (기본은 예상 순수익 순).
줄 끝의 **"거래 요청 보내기"** 를 누르면 `proposed` 거래가 남고 버튼이 `요청 완료` 로 바뀐다.
같은 줄을 다시 눌러도 요청이 중복으로 쌓이지 않는다.

**수급 위험 알림 (SPEC 5.4)** — 품목을 `양파` 로 고르면 SPEC 5.4 예제 그대로:

| 소급 분석 결과 | 물량 |
|---|---|
| 농가 출하 예정량 | **120톤** |
| 도매처 기존 재고량 | **8톤** |
| 전체 공급량 | **128톤** |
| 판매처 구매 수요량 | **100톤** |
| 예상 초과 공급량 | **28톤** |
| 위험 단계 | **위험** |

그 아래 대응 방안 네 줄의 합계가 정확히 **28톤**이다
(식품가공업체 / 학교급식 / 출하 시기 조정 / 지역 공동판매).

**판매처 연계 (SPEC 5.3)** — 토마토 재고 **1,700kg** 이 등급별로 갈라져 붙는다:

| 보유 농산물 | 추천 판매처 |
|---|---|
| 특상품 300kg | 대형마트 |
| 상품 700kg | 학교급식업체 |
| 규격 외 500kg | 소스 가공업체 |
| 판매기한 임박 200kg | 지역 음식점 |

**실시간 시장 분석** — 품목 다섯 줄의 가격/수요 등락률과 시세 지수 추이 그래프.
토마토 줄의 기준일 시세는 **2,450원/kg** 이다.

### 4. 유휴토지 지도 (SPEC 4.4) — `/land/`

1. **요약 지표** 네 개: 운영 중 / 전환 완료 / 오늘 신청량 / AI 추천 거래.
2. 지도 위 마커가 상태 색으로 갈린다 — **A 농지(녹, 상태 최상) · B 농지(황, 상태 양호) ·
   C 농지(적, 개선 필요)**. 범례가 색과 뜻을 같이 적는다.
3. **유휴농지 등록** 버튼 — 토지 소유자 입장에서 위치·면적·용수·임대 조건을 넣으면
   새 필지가 **유휴** 상태로 지도에 올라온다 (SPEC 7.3 첫 단계).
4. **조건 비교** 에 SPEC 5.6 활용 예시를 그대로 넣는다 — 딸기 / 700~1,000평 / 예산 70만 원:

   | 평가 항목 | A 농지 | B 농지 | C 농지 |
   |---|---|---|---|
   | 면적 | 900평 | 1,000평 | 750평 |
   | 월 임대료 | 65만 원 | 55만 원 | 70만 원 |
   | 농업용수 | 확보 | 확보 | **미확보** |
   | 냉장창고 접근성 | 가능 | 제한적 | 가능 |
   | 도매처 거리 | 24km | 38km | 17km |
   | **추천 결과** | **1위** | **2위** | **3위** |

   C 농지가 가장 가까운데도 3위인 이유(농업용수 미확보)가 표 아래 **추천 근거**에 한국어로 나온다.
5. 토양 상태 필터를 `1등급` 으로 좁히면 비교 대상이 A 농지만 남는다.
6. 유휴 상태 농지 줄의 **임대 신청** → 이름을 넣고 접수하면 필지가 **운영 중** 으로 바뀌고,
   지도 색과 요약 지표가 그 자리에서 갱신된다 (SPEC 7.3 마지막 단계).

### 5. 유휴토지 상세 (SPEC 4.5) — `/land/detail/?id=1`

1. 토지 활용률과 유휴토지 정보(재배 작물 · 영농 시작일 · 예상 수확량 · 스마트팜 유형).
   A 농지는 **1동 토마토 재배구역(비닐하우스, 1,000kg)** 과 **2동 딸기 재배구역(유리온실, 400kg)**
   을 갖고 있어 재배구역 선택기로 오갈 수 있다.
2. **실시간 센서** 네 항목 — 시드 기준 온도 **29.4℃**(이탈) / 습도 68%(적정) /
   토양수분 28%(이탈) / 조도 기준의 82%.
3. **이상 수치 알림** 에 원인과 대응 방법이 붙는다 (SPEC 4.5 향후 수정 계획).
4. **센서 변화 그래프** — 항목을 바꾸면 그래프가 따라 바뀐다.
5. **AI 유통 추천 결과** — 이 농지에서 나올 물량의 예상 판매금액과 추천 도매처.

### 6. 스마트팜 자동제어 (SPEC 5.5 / 6 / 7.2)

실물 ESP32 없이 전체 경로를 돌린다:

```bash
docker compose up --build                       # 브로커 + 앱
docker compose exec mosquitto mosquitto_sub -t 'control/command' -v   # 명령 구독 (창 하나)
docker compose --profile sim run --rm sensor-sim --smartfarm 1 --scenario heat_spike
```

시뮬레이터가 `sensor/data` 로 측정값을 올리면 → 서버가 작물 기준값과 비교해 판단하고 →
`control/command` 로 `{"device":"fan","action":"on", ...}` 를 내보낸다. 구독 창에 명령이
찍히고, **농가 대시보드의 자동제어 결과 열과 유휴토지 상세의 센서 카드**가 같이 바뀐다.

시나리오는 `normal` / `heat_spike` / `soil_dry_down` / `dusk` / `all` 이며,
같은 `--seed` 는 항상 같은 스트림을 만든다. 브로커 없이 REST 로만 태우려면
`--transport rest`, 값만 보려면 `--transport print`.

펌웨어의 **오프라인 안전 규칙**(연결이 끊겨도 제한 제어)은 보드 없이 확인할 수 있다:

```bash
./firmware/run_host_tests.sh
```

---

## 2부 · 검증 보고서

SPEC 각 절 → 구현 위치 → 그것을 증명하는 테스트. **미구현·부분 구현은 숨기지 않고 적었다.**

전부 다시 돌리려면:

```bash
cd backend && uv run pytest -q                                                # 백엔드
./firmware/run_host_tests.sh                                                  # 펌웨어 (보드 없이)
docker compose -f docker-compose.test.yml up --build --exit-code-from playwright  # 컨테이너 E2E
```

### 2.1 주요 기능 (SPEC 5)

| SPEC | 기능 | 엔드포인트 / 화면 | 증명하는 테스트 |
|---|---|---|---|
| 5.1 | AI 농산물 시세 예측 | `GET /api/forecast/price` · `POST /api/forecast/shipping-window` · 농가 대시보드 "가격 분석" | `backend/tests/test_price_forecast.py` · `test/specs/farm.spec.ts` (출하일 비교표) |
| 5.2 | 농가 맞춤형 도매처 추천 | `POST /api/recommendations/wholesalers` · `POST /api/deals` · 농가 대시보드 "AI 유통 추천" | `backend/tests/test_wholesaler_rec.py` · `test/specs/farm.spec.ts` · `test/specs/scenario-7-1.spec.ts` |
| 5.3 | 도매처 맞춤 판매처 연계 | `GET /api/wholesalers/{id}/inventory` · `POST /api/recommendations/buyers` · 유통업체 대시보드 "판매처 연계" | `backend/tests/test_buyer_match.py` · `test/specs/distributor.spec.ts` |
| 5.4 | 지역별 수급 위험 조기 알림 | `GET /api/supply-risk` · `GET /api/alerts` · 유통업체 대시보드 "수급 위험" | `backend/tests/test_supply_risk.py` · `test/specs/distributor.spec.ts` |
| 5.5 | 스마트팜 재배환경 통합관리 | `GET /api/smartfarm/{id}/status` · `POST /api/smartfarm/{id}/readings` · 농가 대시보드 · 유휴토지 상세 | `backend/tests/test_smartfarm.py` · `test/specs/farm.spec.ts` · `test/specs/scenario-7-2.spec.ts` |
| 5.6 | 유휴농지 맞춤형 탐색 및 농업인 연결 | `POST /api/parcels/match` · 유휴토지 지도 "조건 비교" | `backend/tests/test_parcel_match.py` · `test/specs/land.spec.ts` |

### 2.2 화면 (SPEC 4)

| SPEC | 화면 | 라우트 | 증명하는 테스트 |
|---|---|---|---|
| 4.1 | 홈 화면 | `/` | `test/specs/home.spec.ts` |
| 4.2 | 농가 대시보드 | `/farm/` | `test/specs/farm.spec.ts` |
| 4.3 | 유통업체 대시보드 | `/distributor/` | `test/specs/distributor.spec.ts` |
| 4.4 | 유휴토지 관리 (지도) | `/land/` | `test/specs/land.spec.ts` |
| 4.5 | 유휴토지 상세 | `/land/detail/?id=<필지 id>` | `test/specs/land.spec.ts` · `test/specs/scenario-7-2.spec.ts` |

SPEC 4 의 "향후 수정 계획" 항목도 이미 들어간 것이 많다 — 4.1 연결 시각화·유형별 메뉴,
4.2 시세 그래프·추천 도매처 목록, 4.3 거리·운송비·품질 등급·추천 이유,
4.4 조건 비교 후 임대 신청, 4.5 이상 수치 알림의 원인·대응.

### 2.3 운영 시나리오 (SPEC 7)

| SPEC | 시나리오 | 증명하는 테스트 |
|---|---|---|
| 7.1 | AI 기반 유통 및 수익 추천 (출하 등록 → 추천 → 거래 선택 → 다음 추천에 반영) | `test/specs/scenario-7-1.spec.ts` |
| 7.2 | IoT 기반 스마트팜 자동제어 (센서 → MQTT → 서버 판단 → 제어 명령 → 화면) | `test/specs/scenario-7-2.spec.ts` (실제 Mosquitto + `tools/sensor_sim.py` 경유) |
| 7.3 | 휴경농지 및 작물 매칭 (농지 등록 → 조건 입력 → 적합도 → 추천 → 매칭 신청) | `test/specs/scenario-7-3.spec.ts` |

7.2 는 `docker-compose.test.yml` 이 Mosquitto 와 시뮬레이터를 함께 띄워
**브로커를 실제로 통과시킨 뒤** Playwright 를 시작한다. REST 로 우회하지 않는다.

### 2.4 시스템 구조 (SPEC 6)

| SPEC 6.2 구성요소 | 구현 | 증명 |
|---|---|---|
| 서버 컴퓨터 | FastAPI (`backend/app`) | `backend/tests/test_api.py` · `test_router_discovery.py` |
| 데이터 전처리 | `app/services/*` · `app/ml/price_model.py` 의 특징 생성 | `backend/tests/test_price_forecast.py` |
| 통합 데이터베이스 | SQLAlchemy 2.0 모델 (`app/models.py`) + 결정론적 시드 | `backend/tests/test_seed.py` |
| AI 의사결정 엔진 | scikit-learn `HistGradientBoostingRegressor` + 점수화 추천 | `backend/tests/test_price_forecast.py` (홀드아웃 MAPE) |
| 유통 매칭 기능 | `app/services/wholesaler_rec.py` (순수익 + 이행률 피드백) | `backend/tests/test_wholesaler_rec.py` |
| 역할별 웹 대시보드 | Next.js 정적 내보내기, 단일 포트 서빙 | `backend/tests/test_static.py` · `test/specs/*.spec.ts` |
| MQTT 실시간 통신 | Mosquitto + `app/services/smartfarm_mqtt.py` | `backend/tests/test_sensor_sim.py` · `test/specs/scenario-7-2.spec.ts` |
| ESP32 엣지 제어기 | `firmware/` (PlatformIO · C++) | `./firmware/run_host_tests.sh` |
| 릴레이 및 구동장치 | 펌웨어 릴레이 핀 제어 + 서버 `control/command` | `firmware/test/test_offline_control` |
| 공공데이터 API | **대체 구현** — 아래 2.6 참고 | — |

### 2.5 예측 정확도 (SPEC 2.3 "시세 예측의 정확도")

`backend/tests/test_price_forecast.py` 가 마지막 60일을 학습에서 완전히 빼고 MAPE 를 잰다.
시드 데이터(충남 논산시, 24개월) 기준:

| 품목 | 홀드아웃 MAPE |
|---|---|
| 토마토 | 3.22% |
| 양파 | 4.91% |
| 딸기 | 4.16% |
| 오이 | 3.28% |
| 배추 | 3.24% |

테스트가 강제하는 상한은 12.0% 이고, "직전 값 그대로" 라는 순진한 예측보다 나은지도 함께 본다.

### 2.6 프로토타입 편차 — 숨기지 않고 적는 것들

| SPEC 이 말한 것 | 실제 구현 | 이유 |
|---|---|---|
| PostgreSQL + PostGIS (SPEC 6.2) | **SQLite** + `app/services/geo.haversine_km` | 심사자가 클론 한 번으로 돌릴 수 있어야 한다. 열 타입은 PostgreSQL 로 그대로 옮겨 가도록 잡았고(enum 은 VARCHAR + CHECK), 거리 계산은 함수 하나에 모아 두어 PostGIS 로 갈아 끼울 자리가 한 곳이다. |
| 공공데이터 API 실시간 수집 (aT 가격, 기상청, 농진청 토양) | **결정론적 시드 데이터** (`backend/app/seed.py`) | 인증키 없이 재현 가능해야 하고, 데모·테스트가 같은 숫자를 봐야 한다. 수집 계층을 붙일 자리는 `market_prices` · `weather_daily` 테이블 그대로다. |
| 실물 ESP32 보드 | 펌웨어는 있고(`firmware/`), 실행은 **시뮬레이터**(`tools/sensor_sim.py`) | 보드 없이 전체 경로(센서 → MQTT → 판단 → 명령)를 돌릴 수 있게 했다. 오프라인 안전 규칙은 호스트 테스트로 검증한다. |
| 로그인 / 사용자 인증 | **없음** — 화면의 사용자 유형 전환으로 대신한다 | SPEC 4.1 이 "향후 수정 계획"으로 둔 항목이라 프로토타입 범위 밖이다. |
| LLM 연동 | `LLM_MOCK` 스위치만 있고 실제 호출 없음 | 추천·예측은 전부 결정론적 모델·규칙으로 구현했다. 추천 근거 문장도 서버가 규칙으로 만든다. |

SPEC 8 은 원문에 없다 (7 다음이 9 다). 누락이 아니라 SPEC 자체가 그렇다.
