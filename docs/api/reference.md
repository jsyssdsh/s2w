# 참조 데이터 (SPEC 6)

지역·품목·도매처 등 모든 기능이 공유하는 조회용 데이터.
라우터: `backend/app/routers/reference.py`

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/regions` | 시군구 목록 | `RegionOut[]` |
| GET | `/api/crops` | 품목 목록 | `CropOut[]` |
| GET | `/api/wholesalers` | 도매처 목록 — 추천·거래 응답의 도매처 id 에 이름을 붙일 때 | `WholesalerOut[]` |

`RegionOut` · `CropOut` 는 여러 기능이 함께 쓰므로
[API.md 의 공용 스키마](../API.md#공용-스키마) 에 둔다.

```jsonc
// WholesalerOut — SPEC 5.2 순수익 계산에 쓰이는 조건을 그대로 노출한다
{ "id": 2, "name": "B 농산물유통", "region_id": 1,
  "lat": 36.44, "lon": 126.78, "unit_price_krw": 2580, "capacity_kg": 1000,
  "fee_rate": 0.03, "transport_cost_per_km": 2000 }
```
