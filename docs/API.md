# API 레퍼런스

모든 엔드포인트는 `/api` 아래에 있고 JSON 을 주고받는다.
규약은 [ARCHITECTURE.md](./ARCHITECTURE.md) 3절 참고.
대화형 문서는 실행 중인 서버의 `/docs` (Swagger UI) 에서 볼 수 있다.

---

## 기능별 문서

기능 하나당 문서 하나다. 상세 표와 스키마는 각 파일 안에 있다.

**기능 bead 는 `docs/api/<feature>.md` 를 새로 만들고, 아래 표에 정렬된 위치로
한 줄만 추가한다.** 한 줄 추가만 하면 union merge 로 충돌 없이 합쳐진다.
이 파일에서 그 외의 것은 건드리지 않는다.

<!-- 파일명 오름차순 · 한 기능당 한 줄 · 추가만 -->

| 문서 | 기능 | SPEC |
|---|---|---|
| [buyer_match](./api/buyer_match.md) | 도매처 맞춤 판매처 연계 | 5.3 |
| [distributor](./api/distributor.md) | 유통업체 대시보드 — AI 추천 농가·거래 요청·시장 분석 | 4.3 |
| [farm](./api/farm.md) | 농가 대시보드·출하 등록 | 4.2 / 7.1 |
| [health](./api/health.md) | 헬스체크 | 6 |
| [parcel_match](./api/parcel_match.md) | 유휴농지 탐색·적합도 매칭 | 5.6 / 7.3 |
| [price_forecast](./api/price_forecast.md) | AI 농산물 시세 예측·출하일 비교 | 5.1 |
| [reference](./api/reference.md) | 지역·품목 참조 데이터 | 6 |
| [smartfarm](./api/smartfarm.md) | 스마트팜 재배환경 통합관리 | 5.5 / 7.2 |
| [supply_risk](./api/supply_risk.md) | 지역별 수급 위험 조기 알림 | 5.4 |
| [wholesaler_rec](./api/wholesaler_rec.md) | 농가 맞춤형 도매처 추천·거래 피드백 | 5.2 / 7.1 |

아직 문서가 없는 기능은 아직 구현되지 않은 것이다. 전체 기능 목록은
[SPEC.md](../SPEC.md) 5장을 본다.

---

## 공용 스키마

여러 기능이 함께 쓰는 모델. 기능 전용 스키마는 그 기능의 문서에 둔다.

```jsonc
// RegionOut
{ "id": 1, "name": "충남 논산시", "lat": 36.187153, "lon": 127.098769 }

// CropOut
{ "id": 1, "name": "토마토", "unit": "kg" }
```

---

## 공급 위험 스키마 (SPEC 5.4)

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
