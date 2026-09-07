# 지역별 수급 위험 조기 알림 (SPEC 5.4)

라우터: `backend/app/routers/supply_risk.py` ·
서비스: `backend/app/services/supply_risk.py` ·
스키마: `backend/app/schemas/supply_risk.py`

## 엔드포인트

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/supply-risk` | 지역·품목의 물량 내역, 위험 단계, 초과 물량 대응 방안 | `SupplyRiskOut` |
| GET | `/api/alerts` | 지역의 품목별 활성 위험 알림 (안정 단계 제외, 위험한 순) | `AlertOut[]` |

### 쿼리 파라미터

| 경로 | 파라미터 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `/api/supply-risk` | `region_id` | ✔ | | 지역 id |
| | `crop_id` | ✔ | | 품목 id |
| | `window_start` | | 시드 기준일 (`2026-08-08`) | 분석 시작일 |
| | `window_end` | | `window_start` + 21일 | 분석 종료일 |
| `/api/alerts` | `region_id` | ✔ | | 지역 id |
| | `as_of` | | 시드 기준일 | 기준일 |
| | `window_days` | | `21` | 기준일부터의 분석 기간 (1–365) |

없는 `region_id` / `crop_id` 는 404, `window_end < window_start` 는 422 다.

### 계산 규칙

- **전체 공급량** = 해당 지역 농가의 창 내 출하 예정량 + 수급권 도매처의 재고량.
  창 시작 전에 유통기한이 끝나는 재고는 세지 않는다.
- **예상 초과 공급량** = 전체 공급량 − 창과 기간이 겹치는 판매처 구매 수요량.
  음수면 공급 부족이라는 뜻이다.
- **수급권**: 시군구 경계가 아니라 지역 중심 반경 50km (`haversine_km`) 안의
  도매처·판매처. 유통 반경이 행정 경계와 다르기 때문이다.
- **위험 단계**: 초과 공급 비율(초과 ÷ 전체 공급) 기준 — 5% 미만 `안정`,
  5%–15% `주의`, 15% 이상 `위험`.
- **대응 방안**: SPEC 5.4 의 네 채널에 우선순위대로 배분한다. 각 채널은 실제
  여력(`capacity_kg`)을 넘겨 받지 않으며, `planned_kg + shortfall_kg == target_kg`
  가 항상 성립한다. 여력이 모자라면 숫자를 맞추지 않고 `shortfall_kg` 로 남긴다.

임계값과 계수는 전부 `backend/app/services/supply_risk.py` 상단의 상수 블록에 있다.

---

## 스키마

```jsonc
// SupplyRiskOut — SPEC 5.4 양파 예제
{
  "region": { "id": 1, "name": "충남 논산시", "lat": 36.187153, "lon": 127.098769 },
  "crop": { "id": 2, "name": "양파", "unit": "kg" },
  "window": { "start": "2026-08-08", "end": "2026-08-29" },
  "volumes": {
    "farm_shipment_kg": 120000,       // 농가 출하 예정량
    "wholesaler_inventory_kg": 8000,  // 도매처 기존 재고량
    "total_supply_kg": 128000,        // 전체 공급량
    "buyer_demand_kg": 100000,        // 판매처 구매 수요량
    "excess_supply_kg": 28000         // 예상 초과 공급량
  },
  "excess_ratio": 0.21875,
  "risk_tier": "위험",                 // 안정 | 주의 | 위험
  "mitigation": {
    "actions": [
      { "channel": "processor",      "label": "식품가공업체 추가 연결", "qty_kg": 12000, "capacity_kg": 12000, "headroom_kg": 0,    "detail": "..." },
      { "channel": "school_meal",    "label": "학교급식 업체 추가 연결", "qty_kg": 7500,  "capacity_kg": 7500,  "headroom_kg": 0,    "detail": "..." },
      { "channel": "shipping_shift", "label": "출하 시기 조정",         "qty_kg": 6000,  "capacity_kg": 6000,  "headroom_kg": 0,    "detail": "..." },
      { "channel": "local_joint",    "label": "지역 공동판매 연계",      "qty_kg": 2500,  "capacity_kg": 12000, "headroom_kg": 9500, "detail": "..." }
    ],
    "target_kg": 28000,      // 처리해야 하는 물량 = max(0, 예상 초과 공급량)
    "planned_kg": 28000,     // 네 채널에 실제 배분된 합계
    "shortfall_kg": 0,       // 여력 부족으로 남은 물량
    "is_fully_covered": true
  }
}

// AlertOut — /api/alerts 의 한 건
{
  "region": { "id": 1, "name": "충남 논산시", "lat": 36.187153, "lon": 127.098769 },
  "crop": { "id": 2, "name": "양파", "unit": "kg" },
  "window": { "start": "2026-08-08", "end": "2026-08-29" },
  "risk_tier": "위험",
  "excess_ratio": 0.21875,
  "total_supply_kg": 128000,
  "buyer_demand_kg": 100000,
  "excess_supply_kg": 28000,
  "shortfall_kg": 0,
  "headline": "충남 논산시 양파 예상 초과 공급 28.0톤 — 위험"
}
```
