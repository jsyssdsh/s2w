<!-- SPEC 4.3 유통업체 대시보드. 라우터: app/routers/distributor.py -->

# 유통업체 대시보드 (SPEC 4.3)

도매처 관점의 집계다. SPEC 5.2 가 "농가 → 어느 도매처" 를 푼다면 이쪽은
"도매처 → 어느 농가 출하" 를 푼다. 계산은 `app/services/distributor.py` 한 곳.

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/distributor/wholesalers` | 대시보드가 고를 수 있는 도매처 목록 (재고 로트 수 포함) | `WholesalerOut[]` |
| GET | `/api/distributor/farm-recommendations` | AI 추천 농가 리스트 + SPEC 4.3 요약 타일 | `FarmRecommendationResponse` |
| POST | `/api/distributor/deal-requests` | "거래 요청 보내기" — `deals` 에 `proposed` 행을 남긴다 (멱등) | `DealRequestOut` (201) |
| GET | `/api/distributor/market` | 실시간 시장 분석 — 품목별 가격/수요 등락률 (실측 시세) | `MarketSnapshotOut` |

### GET `/api/distributor/farm-recommendations`

| 쿼리 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `wholesaler_id` | ✓ | | 도매처 id |
| `crop_id` | | 전체 | 품목으로 거르기 |
| `as_of` | | `2026-08-08` | 기준일 |
| `window_days` | | `21` | 기준일부터 볼 출하 기간 (1–365) |
| `use_forecast` | | `false` | 기준 단가로 SPEC 5.1 **예측** 시세를 쓴다 |

창 안의 출하 중 **아직 거래가 확정되지 않은 것**(`accepted`/`settled` 딜이 없는
출하)만 대상이다. 없는 `wholesaler_id`·`crop_id` 는 404.

한 줄의 계산은 ARCHITECTURE 5절의 순수익 정의를 도매처 쪽으로 옮긴 것이다:

```
매입 가능량    = min(출하량, 도매처 구매 가능량)
예상 판매단가  = 예상 도매 시세 × 등급 계수
예상 판매금액  = 예상 판매단가 × 매입 가능량
운송비         = haversine_km(농가 시군구, 도매처) × transport_cost_per_km
수수료         = 예상 판매금액 × fee_rate
권장 거래가    = (예상 판매금액 − 수수료 − 운송비 − 목표 마진) ÷ 매입 가능량
예상 순수익    = 예상 판매금액 − 수수료 − 매입금액 − 운송비   (≈ 목표 마진)
```

**기준 단가의 기본값은 기준일의 실측 도매 시세**(`price_source: "market"`)다.
`use_forecast=true` 면 SPEC 5.1 예측 시세를 쓰고(`forecast`), 예측이 불가능하면
조용히 실측으로 돌아간다. 시세 이력이 아예 없으면 도매처 고시 단가(`list`)다 —
SPEC 5.2 추천 API 와 같은 규약이다. 기본을 예측으로 두지 않는 이유는 비용이다:
모델 캐시가 비어 있으면 품목 하나 학습에 컨테이너 실측 **~32초**가 걸려서,
대시보드 첫 그림을 거기에 걸 수 없다.

**권장 거래가는 목표 마진에서 역산한 값이다.** 운송비는 물량과 무관하게 한 번
드는 값이라, 값싼 품목이나 먼 농가일수록 농가에 제시할 수 있는 단가가 빠르게
내려간다. 그 값이 예상 판매단가의 `VIABLE_OFFER_RATIO`(0.72) 밑으로 내려가면
농가가 받아들일 제안이 아니라고 보고 `recommended: false` 로 내린다 — 시드
기준으로 같은 양파 출하가 40km 의 B 에서는 추천이고 60km·70km 의 A·C 에서는
아닌 이유다. 등급 계수와 목표 마진율은 `app/services/distributor.py` 상단
상수 블록에만 있다.

정렬은 **추천 대상이 먼저, 그 안에서 예상 순수익이 큰 순**이다. 화면은 이
순서를 기본값으로 쓰고 열 제목으로 다시 정렬한다.

### POST `/api/distributor/deal-requests`

```jsonc
{ "wholesaler_id": 2, "shipment_id": 1,
  "unit_price_krw": null,      // 생략하면 권장 거래가
  "as_of": null }
```

같은 도매처가 같은 출하에 두 번 요청해도 행이 늘지 않는다 (`created: false` 로
단가만 갱신). 이미 `accepted`/`settled` 인 출하는 **409**.

> **`POST /api/deals` (SPEC 5.2) 와의 차이.** 저쪽은 **농가**가 받은 제안 중
> 무엇을 골랐는지를 남기는 기록용이라 상태를 자유롭게 받고 멱등하지 않다.
> 이쪽은 **도매처**가 화면 버튼을 눌러 보내는 제안이라 항상 `proposed` 이고,
> 버튼을 두 번 눌러도 행이 늘지 않으며, 이미 팔린 출하는 409 로 막는다.
> 쓰는 테이블(`deals`)과 피드백 루프는 같다.

### GET `/api/distributor/market`

| 쿼리 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `region_id` | | 첫 지역 (id 순) | 지역 id |
| `as_of` | | 시세 이력의 마지막 날 | 기준일 |
| `lookback_days` | | `7` | 등락률을 재는 기간 (1–365) |

숫자는 `market_prices` 의 **실측 도매 시세**다. 기준일 값과 `lookback_days` 일
전 값을 견줘 등락률을 내고, 수요는 같은 표의 거래량을 대리 지표로 쓴다.
`trend` 는 가격 등락률이 ±`MARKET_FLAT_PCT`(2%) 밖이면 `상승세`/`하락세`,
안이면 `보합`이다. `series` 는 기준일까지의 실적 14일이라 그대로 차트가 된다.
시세 이력이 없는 품목은 조용히 빠진다.

> **여기서 SPEC 5.1 예측 엔진을 부르지 않는다.** 모델 캐시가 비어 있으면 품목
> 하나를 학습하는 데 컨테이너에서 ~32초가 걸린다. 품목 다섯이면 대시보드 첫
> 그림이 몇 분을 기다리게 되므로, 이 패널은 "지금 시장이 어떻게 움직이는가" 를
> 실측으로 답하고, 기간 예측은 그것을 감당할 화면(SPEC 4.2 시세 그래프)이
> `GET /api/forecast/price` 로 직접 쓴다. `backend/tests/test_distributor.py`
> 의 `test_market_does_not_train_a_price_model` 이 이 경계를 지킨다.

## 스키마

```jsonc
// WholesalerOut
{ "id": 2, "name": "B 농산물유통", "region_id": 2, "region_name": "충남 부여군",
  "unit_price_krw": 2580, "capacity_kg": 1000, "fee_rate": 0.03,
  "transport_cost_per_km": 2000, "inventory_lot_count": 5 }

// FarmRecommendationResponse
{
  "wholesaler": { /* WholesalerOut */ },
  "as_of": "2026-08-08", "window_end": "2026-08-29",
  "summary": {
    "supply_count": 5, "recommended_count": 5,
    "expected_amount_krw": 5732000, "expected_net_profit_krw": 869460,
    "supply_qty_kg": 121000, "purchasable_qty_kg": 5000, "requested_count": 1
  },
  "rows": [
    {
      "shipment_id": 5, "farm_id": 1, "farm_name": "울퉁불퉁 청년농장",
      "region_id": 1, "region_name": "충남 논산시",
      "crop_id": 1, "crop_name": "토마토",
      "grade": "special", "grade_label": "특상품", "ship_date": "2026-08-08",
      "qty_kg": 1000, "purchasable_kg": 1000, "unsold_kg": 0,
      "distance_km": 40.0, "transport_cost_krw": 80000,
      "market_price_per_kg": 2450, "graded_price_per_kg": 2695,
      "recommended_price_per_kg": 2210, "offer_pct": 82.0,
      "purchase_cost_krw": 2210000, "resale_revenue_krw": 2695000,
      "fee_krw": 80850, "expected_net_profit_krw": 324150, "margin_pct": 12.03,
      "price_source": "market",       // market | forecast | list
      "requested": true, "recommended": true,
      "reason": "외관과 크기가 균일한 특상품 물량, ..."
    }
  ]
}

// DealRequestOut (201)
{ "id": 3, "shipment_id": 1, "wholesaler_id": 2, "wholesaler_name": "B 농산물유통",
  "farm_name": "논산 양파영농조합", "crop_name": "양파", "qty_kg": 1000,
  "unit_price_krw": 877, "agreed_price_krw": 877000,
  "status": "proposed", "created": true,
  "message": "논산 양파영농조합에 양파 1,000kg 거래 요청을 보냈습니다." }

// MarketSnapshotOut
{
  "region_id": 1, "region_name": "충남 논산시",
  "as_of": "2026-08-08", "lookback_days": 7,
  "rows": [
    { "crop_id": 1, "crop_name": "토마토", "unit": "kg",
      "price_per_kg": 2450, "previous_price_per_kg": 2403,
      "price_change_pct": 1.96,
      "volume_kg": 12000, "previous_volume_kg": 12229,
      "demand_change_pct": -1.88,
      "trend": "보합",              // 상승세 | 하락세 | 보합
      "series": [ { "date": "2026-07-26", "price_per_kg": 2412, "volume_kg": 12186 } ] }
  ]
}
```

## AI 농산물 시세 예측 (SPEC 5.1)
