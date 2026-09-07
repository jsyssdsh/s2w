# 아키텍처 및 개발 규약 (ARCHITECTURE)

이 문서는 **울퉁불퉁 농장 AI (FarmFlow AI)** 의 공유 계약이다.
기능별 작업은 병렬로 진행되므로, 아래 규약을 지켜야 서로 충돌하지 않는다.
SPEC.md 가 "무엇을" 만들지 정의한다면, 이 문서는 "어떻게" 만들지를 정의한다.

---

## 1. 저장소 구조

```
.
├── backend/          FastAPI + Python 3.12 (uv 로 관리)
│   ├── app/
│   │   ├── main.py       앱 조립 — feature 당 include_router 한 줄
│   │   ├── config.py     환경변수 설정
│   │   ├── db.py         엔진 · 세션 · get_session 의존성
│   │   ├── models.py     SQLAlchemy 2.0 도메인 모델 (공유 계약)
│   │   ├── seed.py       결정론적 시드 데이터
│   │   ├── routers/      feature 당 파일 1개 (HTTP 만)
│   │   ├── services/     feature 당 파일 1개 (도메인 로직)
│   │   ├── schemas/      feature 당 파일 1개 (Pydantic v2)
│   │   └── ml/           예측 · 추천 모델
│   └── tests/        pytest
├── frontend/         Next.js App Router + TypeScript + Tailwind (정적 내보내기)
│   ├── app/          라우트
│   ├── components/   공용 UI
│   └── lib/api.ts    단일 타입 API 클라이언트
├── test/             Playwright E2E (BASE_URL 을 읽는다)
└── docs/             ARCHITECTURE.md · API.md
```

컨테이너는 하나다. Dockerfile 이 `frontend/` 를 정적 내보내기 해서 `/app/static`
에 넣고, FastAPI 가 API 와 정적 파일을 같은 포트(8000)에서 서빙한다.

---

## 2. 데이터베이스: SQLAlchemy 2.0 위의 SQLite

SPEC 6.2 는 PostgreSQL + PostGIS 를 요구하지만, 이 프로토타입은 **SQLite** 를 쓴다.
Dockerfile 이 이미 빌드하는 단일 컨테이너 안에서 시스템 전체가 돌아가야 하기 때문이다.

규약:

- 경로는 `DB_PATH` 환경변수에서 온다 (기본값 `/app/db/farmflow.db`).
- **SQLite 에 종속되는 raw SQL 을 쓰지 않는다.** 모든 접근은 SQLAlchemy 2.0
  ORM (`select()`, `Session`) 을 거친다. 그래야 PostgreSQL 전환이 엔진 한 줄
  교체로 끝난다.
- enum 성격의 컬럼은 네이티브 enum 타입이 아니라 **VARCHAR + CHECK** 로 만든다
  (`app/models.py` 의 `_enum()` 헬퍼). PostgreSQL 에서도 그대로 동작한다.
- 거리 계산은 반드시 **`app/services/geo.py` 의 `haversine_km()`** 을 통한다.
  이것이 PostGIS 대체물이며, 나중에 바꿀 유일한 지점이다. 좌표는 평범한
  `lat` / `lon` float 컬럼으로 저장한다.

### 도메인 모델

`backend/app/models.py` 의 테이블·컬럼 이름은 **모든 기능이 공유하는 계약**이다.
컬럼 추가는 자유롭지만 **이름 변경·용도 변경은 금지**한다.

| 테이블 | 내용 | 관련 SPEC |
|---|---|---|
| `users` | 사용자 (farmer/wholesaler/buyer/landowner) | 4 |
| `regions` | 시군구 + lat/lon | 6 |
| `crops` | 품목 + 단위 | 5 |
| `crop_thresholds` | 작물별 적정 생육 기준 | 5.5 |
| `parcels` | 유휴/휴경농지 | 5.6, 7.3 |
| `farms` | 농가 | 4.2 |
| `smartfarms` | 스마트팜 재배구역 | 4.5 |
| `sensor_readings` | 센서 측정값 | 5.5, 7.2 |
| `control_events` | 자동제어 실행 기록 | 5.5, 7.2 |
| `market_prices` | 일별 도매 시세 | 5.1 |
| `weather_daily` | 일별 기상 | 5.1, 6.2 |
| `wholesalers` | 도매처 | 5.2 |
| `buyers` | 최종 판매처 | 5.3 |
| `shipments` | 농가 출하 | 7.1 |
| `inventory` | 도매처 재고 | 5.3, 5.4 |
| `demands` | 판매처 구매 수요 | 5.4 |
| `deals` | 실제 거래 결과 — **추천 피드백 루프** | 6, 7.1 |

`deals` 가 피드백 루프다. 추천 기능은 제안을 `proposed` 로 기록하고, 농가의
선택이 `accepted` / `rejected` / `settled` 로 갱신한다. 다음 추천은 이 이력을
읽어 개선한다 (SPEC 7.1).

---

## 3. API 규약

- 모든 경로는 **`/api`** 아래, JSON 으로 주고받는다.
- 요청·응답 스키마는 **Pydantic v2** (`app/schemas/<feature>.py`).
  ORM 객체는 `model_config = ConfigDict(from_attributes=True)` 로 변환한다.
- `GET /api/health` 는 `{"status":"ok"}` 를 반환한다. 도커 헬스체크가 의존하므로
  **절대 바꾸지 않는다.**
- 새 엔드포인트는 `docs/API.md` 표에 한 줄씩 추가한다.

---

## 4. 파일 배치 — 기능당 파일 하나

병렬 작업이 같은 파일에서 충돌하지 않도록, **기능 하나당 파일 하나**를 지킨다.

```
app/routers/<feature>.py    HTTP 계층만 (경로, 상태코드, 의존성)
app/services/<feature>.py   도메인 로직과 쿼리 — 여기에 실제 계산이 있다
app/schemas/<feature>.py    Pydantic 입출력 모델
app/ml/<feature>.py         학습·추론 모델
```

`app/main.py` 에는 기능별로 **`include_router` 한 줄만** 추가한다. 그 외의
기능별 코드는 넣지 않는다.

프론트엔드도 같은 원칙이다: 화면은 `app/<route>/page.tsx`, 공용 UI 는
`components/`, 서버 호출은 **전부 `lib/api.ts`** 를 거친다 (컴포넌트에서 직접
`fetch` 하지 않는다).

---

## 5. 단위와 반올림

- **금액은 정수 KRW.** float 로 돈을 들고 다니지 않는다.
- **무게는 kg**, **면적은 평(pyeong)**, **거리는 km**, **온도는 ℃**.
- 비율(`fee_rate`)은 0.0–1.0 의 float.
- **반올림은 표현 계층에서만** 한다. 서비스 계층은 계산값을 그대로 반환하고,
  라우터/스키마 또는 프론트엔드에서 표시 형식을 정한다.

순수익 계산은 SPEC 5.2 / 6.2 의 정의를 따른다:

```
예상 순수익 = 판매금액 × (1 − 수수료율) − 운송비
운송비      = haversine_km(농가, 도매처) × transport_cost_per_km
판매금액    = 매입단가 × min(출하량, 구매 가능량)
```

---

## 6. 결정론

테스트와 데모가 매번 같은 숫자를 보게 하려면:

- **비즈니스 로직에 벽시계 시간(`date.today()`, `datetime.now()`)을 쓰지 않는다.**
  대신 `as_of: date` 파라미터를 받고 기본값을 준다.
- **시드 없는 난수를 쓰지 않는다.** 고정 시드의 `random.Random` 을 쓴다.
- 시드 데이터의 기준일은 `app/seed.py` 의 `ANCHOR_DATE` (2026-08-08 — SPEC 5.1
  워크드 예제의 "8월 8일") 이다. 기능 코드의 `as_of` 기본값도 여기에 맞춘다.

---

## 7. 시드 데이터

`backend/app/seed.py` 는 **멱등**하다. DB 가 비어 있을 때만 채우며,
`SEED_ON_START=true` 이면 앱 시작 시, 또는 다음 명령으로 수동 실행한다:

```bash
cd backend && uv run python -m app.seed
```

시드는 SPEC 5장의 워크드 예제를 그대로 재현한다. 기능 beads 는 이 값들을
기대해도 된다:

| SPEC | 시드가 보장하는 것 |
|---|---|
| 5.1 | `ANCHOR_DATE` 의 토마토 시세 = **2,450원/kg**, 품목별 24개월 일별 시계열 |
| 5.2 | 도매처 A/B/C — 2,550원·1,000kg·18만원 / 2,580원·1,000kg·8만원 / 2,700원·800kg·21만원, 수수료 3%. 순수익 순위 **B > A > C** |
| 5.3 | 도매처 재고 토마토 1,700kg = 특상품 300 + 상품 700 + 규격외 500 + 임박 200, 대응 판매처 4종 |
| 5.4 | 양파 출하 120톤 + 재고 8톤 − 수요 100톤 = **초과 28톤** |
| 5.5 | 토마토 기준 22–27℃ / 60–75% / 35–55%, 최신 센서값이 29.4℃ · 68% · 28% · 조도 82% |
| 5.6 | 농지 A/B/C — 900평 65만원 용수확보 냉장가능 24km / 1,000평 55만원 확보 제한적 38km / 750평 70만원 미확보 가능 17km |

도매처 운송비와 농지-도매처 거리는 하드코딩된 숫자가 아니라 **실제 좌표에서
haversine 으로 계산되어 나온다.** 좌표를 옮기면 값이 달라지므로,
`backend/tests/test_seed.py` 가 이를 회귀 테스트로 잡는다.

---

## 8. 프론트엔드

- Next.js **App Router**, TypeScript, Tailwind.
- `next.config.ts` 는 `output: 'export'` — 빌드 결과가 `out/` 에 정적 파일로
  나오고 FastAPI 가 서빙한다. **서버 컴포넌트에서의 런타임 데이터 페칭이나
  서버 액션은 쓸 수 없다.** 데이터는 클라이언트에서 `lib/api.ts` 로 가져온다.
- 모든 사용자 대면 문구는 **한국어**로, SPEC 4장의 표현을 따른다.

---

## 9. 테스트

- **백엔드**: `backend/tests/` pytest. `cd backend && uv run pytest`
- **E2E**: `test/` Playwright, `BASE_URL` 환경변수를 읽는다.
- 컨테이너 전체 검증:
  ```bash
  docker compose -f docker-compose.test.yml up --build --exit-code-from playwright
  ```

기능을 추가하면 그 기능의 SPEC 워크드 예제를 검증하는 테스트를 함께 추가한다.

---

## 10. 환경변수

`.env.example` 참고.

| 변수 | 기본값 | 용도 |
|---|---|---|
| `DB_PATH` | `/app/db/farmflow.db` | SQLite 파일 경로 |
| `MQTT_BROKER_URL` | (없음) | Mosquitto 브로커 — 스마트팜 자동제어 (SPEC 7.2) |
| `SEED_ON_START` | `true` | 빈 DB 를 시작 시 채운다 |
| `LLM_MOCK` | `false` | 결정론적 목 LLM 응답 |
| `STATIC_DIR` | `/app/static` | 내보내진 프론트엔드 위치 |
