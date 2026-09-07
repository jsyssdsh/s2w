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

## 주요 기능

| 기능 | 내용 | SPEC |
|---|---|---|
| AI 시세 예측 | 과거 가격·거래량·기상 데이터로 출하일별 예상 가격을 비교 | 5.1 |
| 도매처 추천 | 매입단가·구매량·운송비·수수료로 예상 순수익을 계산해 순위화 | 5.2 |
| 판매처 연계 | 등급·판매기한·재고를 보고 마트/급식/가공/음식점에 연결 | 5.3 |
| 수급 위험 알림 | 지역 출하량 대비 수요를 비교해 초과 물량과 대응 방안을 제시 | 5.4 |
| 스마트팜 자동제어 | 센서값이 적정 범위를 벗어나면 펌프·환기팬·조명을 MQTT 로 제어 | 5.5 / 7.2 |
| 유휴농지 매칭 | 희망 작물·면적·예산과 용수·냉장창고·거리 조건을 비교해 농지를 추천 | 5.6 / 7.3 |

## 구성

```
backend/    FastAPI + SQLAlchemy 2.0 + SQLite (uv 로 관리)
frontend/   Next.js App Router + TypeScript + Tailwind (정적 내보내기)
test/       Playwright E2E
docs/       아키텍처 규약 · API 레퍼런스
```

빌드하면 프론트엔드가 정적 파일로 내보내져 FastAPI 가 API 와 함께
**단일 컨테이너 · 단일 포트(8000)** 로 서빙한다.

## 실행

### 도커 (권장)

```bash
cp .env.example .env
docker compose up --build
# http://localhost:8000
```

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

## 테스트

```bash
# 백엔드 단위/통합 테스트
cd backend && uv run pytest

# 컨테이너 전체 E2E
docker compose -f docker-compose.test.yml up --build --exit-code-from playwright
```
