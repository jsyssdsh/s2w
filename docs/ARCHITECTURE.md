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
│   │   ├── main.py       앱 조립 — 기능별 코드 없음 (라우터 자동 등록)
│   │   ├── config.py     환경변수 설정
│   │   ├── db.py         엔진 · 세션 · get_session 의존성
│   │   ├── models.py     SQLAlchemy 2.0 도메인 모델 (공유 계약)
│   │   ├── seed.py       결정론적 시드 데이터
│   │   ├── routers/      feature 당 파일 1개 (HTTP 만) — 자동 등록됨
│   │   ├── services/     feature 당 파일 1개 (도메인 로직)
│   │   ├── schemas/      feature 당 파일 1개 (Pydantic v2)
│   │   └── ml/           예측 · 추천 모델
│   └── tests/        pytest
├── frontend/         Next.js App Router + TypeScript + Tailwind (정적 내보내기)
│   ├── app/          라우트
│   ├── components/   공용 UI
│   └── lib/api.ts    단일 타입 API 클라이언트
├── test/             Playwright E2E (BASE_URL 을 읽는다)
└── docs/             ARCHITECTURE.md · API.md(색인) · api/<feature>.md
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
- 새 엔드포인트는 그 기능의 `docs/api/<feature>.md` 에 적는다.
  `docs/API.md` 는 색인이며, 새 기능이면 링크 표에 정렬된 위치로 **한 줄만** 추가한다.

---

## 4. 파일 배치 — 기능당 파일 하나

병렬 작업이 같은 파일에서 충돌하지 않도록, **기능 하나당 파일 하나**를 지킨다.

**기능 하나가 추가하는 파일은 이게 전부다:**

```
backend/app/routers/<feature>.py    HTTP 계층만 (경로, 상태코드, 의존성)
backend/app/services/<feature>.py   도메인 로직과 쿼리 — 여기에 실제 계산이 있다
backend/app/schemas/<feature>.py    Pydantic 입출력 모델
backend/app/ml/<feature>.py         학습·추론 모델 (필요할 때만)
backend/tests/test_<feature>.py     그 기능의 SPEC 워크드 예제 검증
docs/api/<feature>.md               그 기능의 엔드포인트 표와 스키마
```

**`app/main.py` 와 `docs/API.md` 는 수정하지 않는다.** 유일한 예외는
`docs/API.md` 링크 표에 정렬된 위치로 한 줄을 **추가**하는 것뿐이다.

### 라우터 자동 등록

`app/routers/__init__.py` 의 `include_all()` 이 `app/routers/` 안의 모듈을
`pkgutil` 로 훑어 **모듈 이름 순**으로 `router` 를 등록한다. 그래서 기능 추가는
파일 하나를 떨어뜨리는 것으로 끝나고, `app/main.py` 에는 `include_router` 가
한 줄도 없다.

- 모듈 이름 순 정렬이라 경로 해석 순서가 결정론적이다.
- `router` 속성이 없는 모듈은 건너뛴다.
- **임포트가 실패하면 모듈 이름을 로그로 남기고 예외를 다시 던진다.** 라우트가
  조용히 사라지는 것보다 부팅 실패가 낫다.
- 전체 라우트 표는 `backend/tests/test_router_discovery.py` 가 못 박아 둔다.
  라우트가 사라지면 그 테스트가 깨진다.

이 구조 이전에는 기능마다 `main.py` 와 `docs/API.md` 의 같은 지점을 고쳤고,
그래서 병렬 기능 브랜치가 예외 없이 충돌했다 (s2w-3m7).

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

- Next.js **App Router**, TypeScript, Tailwind v4.
- `next.config.ts` 는 `output: 'export'` — 빌드 결과가 `out/` 에 정적 파일로
  나오고 FastAPI 가 서빙한다. **서버 컴포넌트에서의 런타임 데이터 페칭이나
  서버 액션은 쓸 수 없다.** 데이터는 클라이언트에서 `lib/api.ts` 로 가져온다.
  동적 라우트는 `generateStaticParams` 없이는 쓸 수 없다.
- 모든 사용자 대면 문구는 **한국어**로, SPEC 4장의 표현을 따른다.

### 8.1 재사용 규칙 (중요)

화면 bead 는 아래 것들을 **새로 만들지 말고 가져다 쓴다.** 같은 역할의
컴포넌트·포맷터·차트 의존성이 두 벌 생기면 화면마다 숫자 표기와 색이 갈린다.

```
frontend/
├── app/
│   ├── layout.tsx            헤더·푸터·역할 상태 (화면 bead 는 건드리지 않는다)
│   ├── page.tsx              홈 (SPEC 4.1)
│   ├── farm/                 농가 대시보드 (SPEC 4.2)
│   ├── distributor/          유통업체 대시보드 (SPEC 4.3)
│   └── land/                 유휴토지 지도·상세 (SPEC 4.4 / 4.5)
├── components/
│   ├── AppShell.tsx          화면 본문 틀 — 모든 page.tsx 가 이걸로 감싼다
│   ├── SiteHeader.tsx        내비게이션 + 역할 전환기
│   ├── RoleProvider.tsx      useRole() — 사용자 유형 상태
│   ├── ui/                   디자인 시스템
│   ├── charts/               차트 래퍼
│   └── home/                 홈 전용 조각
└── lib/
    ├── api.ts                단일 API 클라이언트
    ├── format.ts             표시 형식
    ├── roles.ts              사용자 유형 + 내비게이션 목록
    ├── useApi.ts             로딩/성공/오류 3-상태 훅
    └── cn.ts                 className 결합
```

**디자인 시스템 — `components/ui`** (`import { ... } from '@/components/ui'`)

| 컴포넌트 | 용도 |
|---|---|
| `Card` / `CardHeader` / `CardBody` / `CardFooter` | 모든 블록의 기본 그릇 |
| `StatTile` / `StatTileGrid` | 요약 지표 (SPEC 4.3 · 4.4). `deltaPct` 로 등락 표시 |
| `Badge` / `StatusBadge` | 상태 배지. `StatusBadge` 는 SPEC 4.4 의 상태 최상(녹)·양호(황)·개선 필요(적) |
| `Table` / `THead` / `TBody` / `TR` / `TH` / `TD` | 비교표. 숫자 열은 `align="right"` |
| `Button` / `ButtonLink` | 버튼과 버튼형 링크 |
| `Select` | 네이티브 `<select>` 래퍼 |
| `EmptyState` | 데이터 없음 · 미구현 라우트 |
| `Skeleton` / `SkeletonText` / `SkeletonTable` | 로딩 자리표시자 |
| `AlertBanner` | AI 알림 · 수급 위험 경고 · API 오류 |

색은 **시맨틱 토큰**만 쓴다 (`bg-surface`, `text-ink`, `text-ink-muted`,
`border-line`, `text-accent`, `text-good` / `warn` / `bad` / `info` 와 `*-soft`
배경). 라이트·다크가 함께 정의돼 있으므로 화면 코드에 `dark:` 분기가 필요 없다.
원시 팔레트(`soil` · `sprout` · `harvest` · `clay` · `water`)는
`app/globals.css` 에서 토큰을 정의할 때만 쓴다.

**포맷터 — `lib/format.ts`**

화면에서 `toLocaleString` 이나 문자열 붙이기를 직접 하지 않는다.

| 함수 | 결과 | 쓰는 곳 |
|---|---|---|
| `formatWon(2450)` | `2,450원` | 금액 |
| `formatWonPerKg(2450)` | `2,450원/kg` | 단가 (SPEC 5.1 · 5.2) |
| `formatManWon(2395000)` | `239만 5,000원` | 만 원 단위 (SPEC 5.2) |
| `formatMoney(v)` | 자릿수에 따라 원/만 원 | 표의 금액 열 기본값 |
| `formatKg` / `formatTon` / `formatWeight` | `1,000kg` / `120톤` | 수량 (SPEC 5.2 · 5.4) |
| `formatPyeong` / `formatKm` / `formatCelsius` | `900평` / `24km` / `29.4℃` | 농지·거리·센서 |
| `formatPercent(68)` / `formatRatio(0.03)` | `68%` / `3%` | 백분율 / 0–1 비율 |
| `formatTrend(5.3)` | `5.3% 상승` | 등락 (SPEC 5.1) |
| `formatDate` / `formatMonthDay` / `formatAxisDate` | `2026년 8월 8일` / `8월 8일` / `8/8` | 날짜·차트 축 |

`YYYY-MM-DD` 문자열은 `new Date()` 로 감싸지 말고 그대로 넘긴다 — 포맷터가
시간대 보정 없이 읽는다.

**차트 — `components/charts`**

**recharts 가 유일한 차트 의존성이다.** 두 번째 차트 라이브러리를 추가하지 말고
`LineChart` / `BarChart` 래퍼를 쓰거나, 필요하면 이 폴더에 래퍼를 늘린다.
계열색은 `--color-series-1..5` 다섯 개뿐이고 다크 모드에서 자동으로 바뀐다.
축 라벨은 한국어로 넣고, 값 포맷은 `formatValue` 에 `lib/format.ts` 함수를 넘긴다.

**데이터 로딩**

```tsx
'use client';
const crops = useApi(useCallback((opts) => getCrops(opts), []));
if (crops.status === 'loading') return <SkeletonTable />;
if (crops.status === 'error') return <AlertBanner tone="bad">{errorMessage(crops.error)}</AlertBanner>;
```

`lib/api.ts` 에는 **자기 SPEC 절 섹션만** 추가한다 — 공통 영역(요청 헬퍼,
`ApiError` / `NetworkError`, `AsyncState`)은 건드리지 않는다.

**내비게이션과 사용자 유형**

새 화면은 `lib/roles.ts` 의 `NAV_ITEMS` 에 한 줄 추가하면 헤더·홈 카드·유형별
메뉴에 함께 나온다. 유형이 필요한 화면은 `useRole()` 을 쓴다.

---

## 9. 테스트

- **백엔드**: `backend/tests/` pytest. `cd backend && uv run pytest`
- **프론트엔드**: 타입·린트·정적 빌드가 게이트다.
  `cd frontend && npm run typecheck && npm run lint && npm run build`
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

---

## 11. 스마트팜 자동제어 계약 (SPEC 5.5 / 7.2)

판단은 **전부 서버가 한다.** ESP32 는 측정하고 발행하고, 명령을 받아 릴레이를
닫는 장치다. 기준값(`crop_thresholds`)과 히스테리시스 상수는 서버 한 곳
(`backend/app/services/smartfarm.py` 최상단)에만 있고, 펌웨어에 복제하지 않는다.

### 11.1 MQTT 토픽

| 토픽 | 방향 | 페이로드 |
|---|---|---|
| `sensor/data` | ESP32 → 서버 | `{"smartfarm_id":1,"ts":"...","temp_c":29.4,"humidity_pct":68.0,"lux":12300,"soil_moisture_pct":28.0}` |
| `control/command` | 서버 → ESP32 | `{"smartfarm_id":1,"device":"fan","action":"on","metric":"temp_c","reason":"...","ts":"..."}` |

`ts` 는 생략 가능하며 그때는 서버 수신 시각을 쓴다. 브로커 주소는
`MQTT_BROKER_URL` 이고, **비어 있으면 브리지 전체가 비활성**이다 (REST 전용).
브로커가 죽어 있어도 앱은 뜨고 REST 수집·자동제어는 그대로 동작한다 —
연결은 백그라운드에서 지수 백오프로 재시도한다.

REST `POST /api/smartfarm/{id}/readings` 와 MQTT 구독자는 **같은**
`app.services.smartfarm.ingest_reading()` 을 부른다. 두 경로가 갈라질 수 없다.

### 11.2 서버 판단 규칙

- **이상이 지속될 때만 작동한다.** 최근 `SUSTAINED_BREACH_READINGS` 회 연속으로
  기준을 벗어나야 가동한다 (SPEC 5.5 "이상이 지속되면"). 스파이크 한 번은 무시.
- **히스테리시스.** 정지 기준을 가동 기준보다 여유분만큼 안쪽으로 당겨 기준선
  근처에서 장치가 깜빡이지 않게 한다. 여기에 `MIN_ON_TIME` 최소 가동시간이 더해진다.
- **상태는 DB 에서 파생한다.** 장치의 현재 상태는 `control_events` 의 장치별
  최신 행이다. 별도 in-memory 상태가 없으므로 서버를 재시작해도 같은 답이 나온다.
- **환기팬 충돌 해소 순서는 온도 우선이다.** ① 온도 상한 초과 → 습도가 하한
  미만이어도 환기(고온 피해가 더 빠르다) ② 온도가 적정 범위일 때만 습도 상한
  초과로 환기, 단 온도가 하한 미만이면 환기가 더 냉각시키므로 가동하지 않는다
  ③ 습도 하한 미만은 제어 대상이 아니다(가습 장치가 없고 환기는 더 건조시킨다)
  ④ 정지는 온도·습도가 **둘 다** 안쪽으로 돌아왔을 때만.

### 11.3 ESP32 오프라인 안전 규칙 (SPEC 6 "인터넷 연결이 끊겨도 제한적으로 제어")

펌웨어 bead 는 이 규칙에 맞춰 구현한다. 목표는 **작물을 살리는 것**이지 서버를
흉내내는 것이 아니다. 오프라인 제어는 보수적이고 시간 제한이 있다.

1. **오프라인 판정** — 브로커 연결이 끊겼거나, 마지막 `control/command` 수신
   이후 측정 주기의 3배(기본 90초)가 지나면 오프라인 모드로 들어간다.
   복귀 즉시 판단 권한을 서버에 되돌린다.
2. **기준값 출처** — 마지막으로 받은 `control/command` 와 함께 NVS 에 저장해 둔
   작물 기준값 사본을 쓴다. 사본이 없으면 펌웨어 컴파일 상수(보수적 기본값).
3. **허용되는 제어는 두 가지뿐이다.**
   - **워터펌프**: 토양수분이 하한보다 **5%p 이상** 낮을 때만, 한 번에 최대
     5분 가동하고 최소 30분 쉰다. 하루 6회를 넘기지 않는다. 오프라인 상태에서
     센서가 고장 나면 침수가 가장 큰 위험이므로 상한을 건다.
   - **환기팬**: 온도가 상한 **+2℃** 를 넘으면 가동하고, 상한 아래로
     내려오면 정지한다. 고온은 몇 시간이면 작물을 잃으므로 시간 제한을 두지 않는다.
4. **조명은 오프라인에서 제어하지 않는다.** 광량 부족은 즉각적인 피해가 아니고,
   끊긴 상태에서 켜 두면 전력만 소모한다.
5. **페일세이프**
   - 부팅 시 모든 릴레이는 OFF 에서 시작한다.
   - 센서 읽기가 실패하면 **아무것도 하지 않는다.** 값이 없으면 동작도 없다.
   - 워치독 타이머로 펌웨어가 멈춘 채 릴레이가 닫혀 있는 상태를 막는다.
6. **복귀 보고** — 오프라인 동안 수행한 동작은 복귀 후 서버에 보고한다
   (`POST /api/smartfarm/{id}/controls`, `reason` 에 `오프라인 안전 제어` 표기).
   그래야 `control_events` 가 실제 장치 이력과 어긋나지 않는다.
