# API 레퍼런스

모든 엔드포인트는 `/api` 아래에 있고 JSON 을 주고받는다.
규약은 [ARCHITECTURE.md](./ARCHITECTURE.md) 3절 참고.

각 기능 bead 는 자기 엔드포인트 행을 이 표에 추가한다.
대화형 문서는 실행 중인 서버의 `/docs` (Swagger UI) 에서 볼 수 있다.

## 기반 (SPEC 6)

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/health` | 헬스체크 (도커 healthcheck 가 사용) | `{"status":"ok"}` |
| GET | `/api/regions` | 시군구 목록 | `RegionOut[]` |
| GET | `/api/crops` | 품목 목록 | `CropOut[]` |

## AI 농산물 시세 예측 (SPEC 5.1)

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/forecast/price` | 일별 시세 예측 + 차트용 최근 실적 | `PriceForecastOut` |
| POST | `/api/forecast/shipping-window` | 출하일 비교표 (SPEC 5.1 활용 예시) | `ShippingWindowOut` |

### GET `/api/forecast/price`

| 쿼리 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `crop_id` | ✓ | | 품목 ID |
| `region_id` | ✓ | | 지역 ID |
| `horizon` | | `14` | 예측 지평 (1~30일) |
| `as_of` | | 시세 이력의 마지막 날 | 예측 기준일 |

`actuals` 는 기준일까지의 최근 60일 실적, `forecast` 는 기준일 다음 날부터
`horizon` 일까지의 일별 예측이다. 두 배열을 이어 붙이면 그대로 차트가 된다.

시세 이력이 없는 `(crop_id, region_id)` 조합은 **404**, 범위를 벗어난
`horizon`·`as_of` 는 **422**.

### POST `/api/forecast/shipping-window`

요청 본문:

```jsonc
{
  "crop_id": 1,
  "region_id": 1,
  "qty_kg": 1000,
  "candidate_dates": ["2026-08-08", "2026-08-10", "2026-08-17"],  // 첫 날짜가 기준
  "as_of": null                                                   // 생략 가능
}
```

응답의 `rows` 는 후보일마다 한 줄이고, SPEC 5.1 비교표의 각 행에 대응한다:

| SPEC 표의 항목 | 응답 필드 |
|---|---|
| 예상 도매가격 | `expected_price_per_kg` |
| 예상 판매금액 | `expected_revenue_krw` (= 예상 단가 × `qty_kg`) |
| 현재 대비 가격 변동 | `change_pct_vs_baseline` (첫 행 = 기준 = `0.0`) |
| 예상 시장 상황 | `supply_outlook` |
| 시스템 안내 | `guidance` |

`supply_outlook` 은 예상 출하량을 **계절 평년 거래량**(같은 연중 시기 ±7일 평균)과
견줘 정한다 — 평년의 97% 미만이면 `공급량 감소 예상`, 103% 초과면
`공급량 증가 예상`, 그 사이면 `공급량 보통`.

`guidance` 는 기준 대비 변동률로 정한다 — 상승이면 `출하 유지 권장`,
−3% 아래로 하락이면 `조기 출하 검토`, 그 밖에는 `즉시 출하 가능`.
임계값은 `app/services/price_forecast.py` 상단 상수 블록 한 곳에 모여 있다.

기준일 당일(지평 0)은 예측이 아니라 **실측 시세**를 그대로 쓴다. 그래서
2026-08-08 토마토 기준 행은 SPEC 그대로 2,450원/kg · 245만 원이 나온다.

### 예측 모델과 정확도 (SPEC 2.3)

`app/ml/price_model.py` 는 scikit-learn `HistGradientBoostingRegressor` 를
`(crop_id, region_id)` 별로 학습한다 (SPEC 6.2 의 "AI 의사결정 엔진").

- **특징**: 가격 시차 1·7·14·30일, 가격/거래량 7·30일 이동평균, 당일 거래량,
  당일 평균기온·강수량·일조시간, 예측 대상일의 계절성(day-of-year sin/cos),
  예측 지평. 전부 기준일 시점에 알 수 있는 값이라 미래 정보 누설이 없다.
- **결정론**: 고정 시드 + 조기중단 없음. 같은 데이터를 두 번 학습하면 예측값이
  완전히 같다 (`tests/test_price_forecast.py`).
- **캐시**: 학습된 모델은 `DB_PATH` 옆 `models/price_model_c<crop>_r<region>.joblib`
  로 저장되고, 시세 데이터의 지문이 바뀌면 자동으로 다시 학습한다.
- **백테스트**: 마지막 **60일**을 학습에서 완전히 제외하고 MAPE 를 측정한다.
  같은 홀드아웃의 잔차가 응답의 `lower/upper_price_per_kg` (약 95% 구간)을 만든다.

시드 데이터(충남 논산시, 24개월) 기준 홀드아웃 MAPE:

| 품목 | MAPE |
|---|---|
| 토마토 | 3.22% |
| 양파 | 4.91% |
| 딸기 | 4.16% |
| 오이 | 3.28% |
| 배추 | 3.24% |

테스트가 강제하는 상한은 `MAPE_CEILING_PCT = 12.0%` 이고, 같은 테스트가
"직전 값 그대로" 라는 순진한 예측보다 나은지도 함께 확인한다.

## 농가 맞춤형 도매처 추천 (SPEC 5.2)

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| _(미구현)_ | | | |

## 도매처 맞춤 판매처 연계 (SPEC 5.3)

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/wholesalers/{id}/inventory` | 도매처 재고 로트 — 등급·수량·판매기한·잔여일. 쿼리 `crop_id`(선택), `as_of`(기본 2026-08-08). 판매기한이 짧은 순 | `InventoryLotOut[]` |
| POST | `/api/recommendations/buyers` | 재고 로트별 추천 판매처. 본문 `BuyerMatchRequest` | `BuyerMatchResponse` |

```jsonc
// BuyerMatchRequest
{ "wholesaler_id": 2, "crop_id": 1, "as_of": "2026-08-08" }

// InventoryLotOut
{
  "id": 4, "wholesaler_id": 2, "crop_id": 1, "crop_name": "토마토",
  "grade": "near_expiry", "grade_label": "판매기한 임박", "qty_kg": 200,
  "expiry_date": "2026-08-10", "days_remaining": 2, "near_expiry": true
}

// BuyerMatchResponse
{
  "wholesaler_id": 2, "wholesaler_name": "B 농산물유통",
  "crop_id": 1, "crop_name": "토마토", "as_of": "2026-08-08",
  "total_qty_kg": 1700, "total_allocated_kg": 1700, "total_unallocated_kg": 0,
  "lots": [
    {
      "lot": { /* InventoryLotOut */ },
      "allocated_kg": 200, "unallocated_kg": 0,
      "recommendations": [
        {
          "buyer_id": 4, "buyer_name": "계룡 향토음식점",
          "buyer_type": "restaurant", "buyer_type_label": "지역 음식점",
          "distance_km": 42.2, "demand_kg": 200, "matched_qty_kg": 200,
          "score": 0.8541, "reason": "판매기한 임박 200kg 중 200kg — ..."
        }
      ]
    }
  ]
}
```

매칭 규칙: 등급(특상품→대형마트 / 상품→학교급식 / 규격 외→가공업체 /
임박→음식점·로컬푸드)이 사전확률이고, 최종 순위는 **수요 적합도 · 거리 ·
긴급도** 를 합한 점수다. 잔여 판매기한이 3일 이하인 로트는 명목 등급과
무관하게 "임박" 으로 취급되어 먼저 배정된다 — 긴급도가 등급을 지배한다.
한 응답 안에서 판매처의 수요량은 로트를 가로질러 차감되므로 이중 배정이
생기지 않는다.

## 지역별 수급 위험 조기 알림 (SPEC 5.4)

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| _(미구현)_ | | | |

## 스마트팜 재배환경 통합관리 (SPEC 5.5 / 7.2)

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| _(미구현)_ | | | |

## 유휴농지 탐색·적합도 매칭 (SPEC 5.6 / 7.3)

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| POST | `/api/parcels/match` | 희망 작물·면적·예산으로 유휴농지 적합도 순위 산출 | `ParcelMatchResponse` |
| GET | `/api/parcels/geojson?region_id=` | 지도용 GeoJSON (SPEC 4.4, 상태 색상 포함) | `ParcelFeatureCollection` |
| GET | `/api/parcels/summary?region_id=` | 요약 지표 — 운영 중 / 전환 완료 / 오늘 신청량 / AI 추천 거래 (SPEC 4.4) | `ParcelSummaryOut` |
| GET | `/api/parcels/{id}` | 유휴토지 상세 (SPEC 4.5) | `ParcelDetailOut` |
| POST | `/api/parcels/{id}/applications` | 임대(매칭) 신청 — 필지를 `idle` → `operating` 으로 전환 (SPEC 7.3) | `ParcelApplicationResponse` (201) |

### 적합도 점수 (SPEC 5.6)

여섯 개 평가 축의 가중합이며, 가중치는
`app/services/parcel_match.py` 의 `WEIGHTS` 한 블록에만 있고 응답에도 실린다.

| 축 (`axis`) | 항목 | 가중치 | 점수 정의 |
|---|---|---|---|
| `water` | 농업용수 | 0.30 | 확보 1.0 / 미확보 0.0 |
| `crop` | 작물 적합도 | 0.20 | 기상 적합일 비율 × 0.6 + 토양 등급 × 0.4 |
| `area` | 면적 | 0.15 | 희망 범위 안이면 1.0, 벗어난 비율만큼 감점 |
| `rent` | 월 임대료 | 0.15 | `1 − 임대료 ÷ 예산` (예산 이상이면 0.0) |
| `distance` | 도매처 거리 | 0.12 | `1 − 거리 ÷ 60km` (`haversine_km` 기준) |
| `cold_storage` | 냉장창고 접근성 | 0.08 | 가능 1.0 / 제한적 0.5 / 미확보 0.0 |

농업용수는 **하드 페널티**다. SPEC 5.6 비교표에서 C 농지가 가장 짧은 도매처
거리(17km)를 가지고도 3위인 이유이며, A 농지에서 용수를 빼면 B 농지 아래로
떨어진다 (`backend/tests/test_parcel_match.py`).

기상 적합도는 기준일(`as_of`, 기본 `ANCHOR_DATE`) 직전 365일의 `weather_daily`
평균기온이 작물 생육 기준 온도 범위에 든 날의 비율이다.

---

## 공용 스키마

```jsonc
// RegionOut
{ "id": 1, "name": "충남 논산시", "lat": 36.187153, "lon": 127.098769 }

// CropOut
{ "id": 1, "name": "토마토", "unit": "kg" }
```

## 시세 예측 스키마 (SPEC 5.1)

```jsonc
// PriceForecastOut (GET /api/forecast/price)
{
  "crop_id": 1, "crop_name": "토마토",
  "region_id": 1, "region_name": "충남 논산시",
  "as_of": "2026-08-08",
  "horizon_days": 14,
  "model": { "mape_pct": 3.22, "backtest_days": 60,
             "trained_through": "2026-08-08", "max_horizon_days": 30 },
  "actuals": [ { "date": "2026-08-08", "price_per_kg": 2450, "volume_kg": 12000 } ],
  "forecast": [ { "date": "2026-08-09", "horizon_days": 1,
                  "expected_price_per_kg": 2373,
                  "lower_price_per_kg": 2194, "upper_price_per_kg": 2552,
                  "expected_volume_kg": 12403,
                  "supply_outlook": "공급량 보통" } ]
}

// ShippingWindowOut (POST /api/forecast/shipping-window)
{
  "crop_id": 1, "crop_name": "토마토",
  "region_id": 1, "region_name": "충남 논산시",
  "qty_kg": 1000,
  "as_of": "2026-08-08",
  "baseline_date": "2026-08-08",
  "model": { "mape_pct": 3.22, "backtest_days": 60,
             "trained_through": "2026-08-08", "max_horizon_days": 30 },
  "rows": [ { "date": "2026-08-08", "horizon_days": 0,
              "expected_price_per_kg": 2450,
              "expected_revenue_krw": 2450000,
              "change_pct_vs_baseline": 0.0,
              "lower_price_per_kg": 2450, "upper_price_per_kg": 2450,
              "expected_volume_kg": 12000,
              "supply_outlook": "공급량 감소 예상",
              "guidance": "즉시 출하 가능",
              "is_baseline": true } ]
}
```


## 유휴농지 스키마 (SPEC 5.6 / 7.3)

```jsonc
// POST /api/parcels/match 요청 — region_id·limit·as_of 는 선택
{
  "crop_id": 3,
  "area_min_pyeong": 700,
  "area_max_pyeong": 1000,
  "budget_krw_per_month": 700000,
  "region_id": null,
  "limit": null,
  "as_of": null
}

// ParcelMatchResponse
{
  "crop_id": 3,
  "crop_name": "딸기",
  "as_of": "2026-08-08",
  "weights": { "water": 0.3, "crop": 0.2, "area": 0.15,
               "rent": 0.15, "distance": 0.12, "cold_storage": 0.08 },
  "results": [
    {
      "rank": 1,
      "parcel_id": 1,
      "name": "A 농지",
      "region_id": 2,
      "region_name": "충남 부여군",
      "area_pyeong": 900,
      "monthly_rent_krw": 650000,
      "water_access": true,
      "cold_storage_access": "possible",   // possible | limited | none
      "soil_grade": "1등급",
      "status": "operating",                // idle | operating | converted
      "condition": "best",                  // best | good | needs_improvement
      "lat": 36.288833,
      "lon": 126.97254,
      "nearest_wholesaler": { "id": 2, "name": "B 농산물유통", "distance_km": 24.0 },
      "total_score": 0.7243,
      "axes": [
        { "axis": "water", "label": "농업용수", "value": "확보",
          "score": 1.0, "weight": 0.3, "weighted": 0.3 }
        // ... 여섯 축 전부
      ],
      "reason": "농업용수 확보, 면적 900평으로 ... 항목이 우수합니다."
    }
  ]
}

// ParcelFeatureCollection — 표준 GeoJSON. 좌표는 [경도, 위도].
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": { "type": "Point", "coordinates": [126.97254, 36.288833] },
      "properties": {
        "id": 1, "name": "A 농지", "region_id": 2, "region_name": "충남 부여군",
        "area_pyeong": 900, "monthly_rent_krw": 650000, "water_access": true,
        "cold_storage_access": "possible", "soil_grade": "1등급",
        "status": "operating", "status_label": "운영 중",
        "condition": "best", "condition_label": "상태 최상",
        "color": "green",              // green(녹) | amber(황) | red(적)
        "color_hex": "#16a34a"
      }
    }
  ]
}

// ParcelSummaryOut — SPEC 4.4 요약 지표
{
  "region_id": null, "region_name": null,
  "total_count": 3, "idle_count": 1,
  "operating_count": 1, "converted_count": 1,
  "applications_today": 0, "ai_recommended_deals": 2,
  "land_utilization_rate": 0.717,   // 활용 중 면적 ÷ 전체 유휴농지 면적
  "as_of": "2026-08-08"
}

// ParcelDetailOut — SPEC 4.5 (요약)
{
  "id": 1, "name": "A 농지", "region_name": "충남 부여군",
  "area_pyeong": 900, "monthly_rent_krw": 650000, "soil_grade": "1등급",
  "water_access": true, "cold_storage_label": "가능",
  "status_label": "운영 중", "condition_label": "상태 최상",
  "color": "green", "color_hex": "#16a34a",
  "owner": { "id": 2, "name": "박토지", "phone": "010-1000-0002" },
  "nearby_facilities": [
    { "kind": "wholesaler", "name": "B 농산물유통", "distance_km": 24.0,
      "note": "매입단가 2,580원/kg" },
    { "kind": "cold_storage", "name": "냉장창고", "distance_km": null, "note": "가능" }
  ],
  "smartfarms": [
    { "id": 2, "name": "2동 딸기 재배구역", "type": "유리온실",
      "crop_id": 3, "crop_name": "딸기",
      "started_on": "2026-06-09", "expected_yield_kg": 400 }
  ],
  "land_utilization_rate": 0.5455,
  "application_count": 0
}

// POST /api/parcels/{id}/applications 요청 — crop_id 와 applicant_name 만 필수
{
  "crop_id": 3,
  "applicant_name": "김청년",
  "applicant_id": null,
  "phone": "010-1000-0001",
  "lease_months": 24,
  "message": "딸기 스마트팜을 조성하고 싶습니다.",
  "match_score": 0.4038,
  "applied_on": null
}

// ParcelApplicationResponse (201)
{
  "application": {
    "id": 1, "parcel_id": 3, "crop_id": 3, "applicant_id": null,
    "applicant_name": "김청년", "phone": "010-1000-0001",
    "lease_months": 24, "message": "딸기 스마트팜을 조성하고 싶습니다.",
    "match_score": 0.4038, "status": "pending",   // pending | accepted | rejected
    "applied_on": "2026-08-08"
  },
  "parcel_status": "operating",
  "parcel_status_label": "운영 중"
}
```

## 오류 응답

FastAPI 기본 형식을 따른다.

```jsonc
{ "detail": "..." }
```

| 상태 코드 | 의미 |
|---|---|
| 404 | 리소스 없음 |
| 409 | 상태 충돌 — 예: 유휴가 아닌 필지에 임대 신청 |
| 422 | 요청 검증 실패 (Pydantic) |
