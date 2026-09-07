# AI 농산물 시세 예측·출하일 비교 (SPEC 5.1)

라우터: `backend/app/routers/price_forecast.py` ·
서비스: `backend/app/services/price_forecast.py` ·
스키마: `backend/app/schemas/price_forecast.py` ·
모델: `backend/app/ml/price_model.py`

## 엔드포인트

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
---

## 스키마

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

