# 농가 맞춤형 도매처 추천 (SPEC 5.2)

라우터: `backend/app/routers/wholesaler_rec.py` ·
서비스: `backend/app/services/wholesaler_rec.py` ·
스키마: `backend/app/schemas/wholesaler_rec.py`

## 엔드포인트

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| POST | `/api/recommendations/wholesalers` | 도매처별 예상 순수익을 계산해 순위와 근거를 반환 | `WholesalerRecommendationOut` |
| POST | `/api/deals` | 농가의 실제 거래 선택을 기록 (피드백 루프) | `DealOut` (201) |
| GET | `/api/deals?shipment_id=&wholesaler_id=` | 기록된 거래 이력 | `DealOut[]` |

### 예상 순수익 계산

SPEC 6.2 의 정의를 그대로 따른다. 계산은 `app/services/wholesaler_rec.py` 한 곳에 있다.

```
구매량(sellable_kg) = min(출하량, 도매처 구매 가능량)
판매금액(gross)     = 매입단가 × 구매량
운송비(transport)   = haversine_km(농가 시군구, 도매처) × transport_cost_per_km
수수료(fee)         = 판매금액 × fee_rate
예상 순수익         = 판매금액 − 운송비 − 수수료
```

`farms` 에 좌표 컬럼이 없으므로 운송 출발점은 **소속 시군구 좌표**다.
구매 가능량을 넘는 물량은 `unsold_kg` 로 돌려주므로 UI 가 잔여 물량을 경고할 수 있다.

시드 기준(토마토 1,000kg, 2026-08-08 출하)의 결과:

| 도매처 | 단가 | 구매량 | 운송비 | 수수료 | 예상 순수익 | 순위 |
|---|---|---|---|---|---|---|
| B 농산물유통 | 2,580원/kg | 1,000kg | 80,000원 (40km) | 77,400원 | **2,422,600원** | 1위 |
| A 청과도매 | 2,550원/kg | 1,000kg | 180,000원 (60km) | 76,500원 | **2,293,500원** | 2위 |
| C 도매시장 | 2,700원/kg | 800kg | 210,000원 (70km) | 64,800원 | **1,885,200원** | 3위 |

> **SPEC 5.2 표의 A 행 오기**: SPEC 은 A 의 예상 순수익을 239만 5,000원으로 적었지만,
> 같은 행의 단가·구매량·운송비로는 수수료를 0 으로 놓아도 2,550,000 − 180,000 =
> 237만원이 상한이라 그 값이 나올 수 없다. 수수료 3% 를 반영한 실제 값은
> **229만 3,500원**(자릿수가 뒤바뀐 오기로 보인다)이며, B·C 는 SPEC 과 정확히
> 일치한다. SPEC 이 요구하는 결론인 순위 **B > A > C** 는 그대로다.

### 거래 피드백 루프 (SPEC 7.1)

농가가 실제로 고른 거래처는 `POST /api/deals` 로 `deals` 에 남고, 다음 추천에
**도매처별 이행률(reliability)** 로 반영된다.

```
이행률 = (이행 건수 + 4 × 1.0) / (결론난 건수 + 4)
정렬 기준값 = 예상 순수익 × (1 − 0.15 × (1 − 이행률))
```

- 이행 = `accepted` / `settled`, 결론 = 거기에 `rejected` 를 더한 것.
  아직 `proposed` 인 제안은 분모에 넣지 않는다 — 추천을 많이 받은 도매처가
  벌점을 받으면 안 되기 때문이다.
- 사전확률 4건을 깔아 두므로 **이력이 없는 도매처의 이행률은 1.0(중립)** 이고,
  시드 상태에서는 순위가 예상 순수익 그대로다.
- 감점 폭 상한은 15%. 근소한 차이는 뒤집지만 SPEC 5.2 기본 순위는 흔들지 않는다.
- 한 도매처를 `accepted` / `settled` 로 기록하면 **같은 출하의 나머지 `proposed`
  행은 `rejected` 로 닫힌다.** 이것이 다음 추천에 들어가는 음의 신호다.
- `decided_on` 을 생략하면 출하일을 쓴다 (벽시계 시간 금지 — ARCHITECTURE 6절).

임계값과 가중치는 `app/services/wholesaler_rec.py` 상단 상수 블록에 모여 있다.

### 예측 시세 연동 (SPEC 5.1)

`use_forecast: true` 를 주면 도매처 고시 단가 대신 출하일의 **예측 시세**를 단가로
쓴다. 예측 서비스(`app/services/price_forecast.forecast_price_per_kg`)가 아직 없거나
실패하면 고시 단가로 조용히 되돌아가고, `price_source` 가 `static` 으로 남으며
`notes` 에 이유가 들어간다. 도매처 고시 단가는 언제나 `list_unit_price_krw` 로
함께 반환한다.

---

## 스키마

```jsonc
// WholesalerRecommendationIn — POST /api/recommendations/wholesalers
{
  "farm_id": 1,
  "crop_id": 1,
  "qty_kg": 1000,
  "ship_date": "2026-08-08",
  "use_forecast": false,   // 선택: 예측 시세를 단가로 사용
  "limit": null            // 선택: 상위 N개만
}

// WholesalerRecommendationOut
{
  "farm_id": 1,
  "farm_name": "울퉁불퉁 청년농장",
  "crop_id": 1,
  "crop_name": "토마토",
  "qty_kg": 1000,
  "ship_date": "2026-08-08",
  "price_source": "static",        // "static" | "forecast"
  "notes": [],                     // 잔여 물량·예측 대체 등 안내 문구
  "candidates": [
    {
      "rank": 1,
      "wholesaler_id": 2,
      "name": "B 농산물유통",
      "distance_km": 40.0,
      "unit_price_krw": 2580,      // 계산에 쓴 단가
      "list_unit_price_krw": 2580, // 도매처 고시 단가
      "capacity_kg": 1000,
      "sellable_kg": 1000,
      "unsold_kg": 0,
      "gross_krw": 2580000,
      "transport_cost_krw": 80000,
      "fee_rate": 0.03,
      "fee_krw": 77400,
      "net_profit_krw": 2422600,
      "ranking_score_krw": 2422600, // 이행률 반영 정렬 기준값
      "reliability": { "score": 1.0, "fulfilled": 1, "decided": 1, "proposed_total": 2 },
      "reason": "1위 · 예상 순수익 242만 2,600원 — 단가 2,580원/kg 으로 ..."
    }
  ]
}

// DealIn — POST /api/deals
{
  "shipment_id": 5,
  "wholesaler_id": 2,
  "status": "accepted",       // proposed | accepted | rejected | settled
  "agreed_price_krw": null,   // 생략 시 단가 × min(출하량, 구매 가능량)
  "decided_on": null          // 생략 시 출하일
}

// DealOut
{
  "id": 3,
  "shipment_id": 5,
  "wholesaler_id": 2,
  "agreed_price_krw": 2580000,
  "status": "accepted",
  "decided_on": "2026-08-08"
}
```
