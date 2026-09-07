# 농가 대시보드 · 출하 등록 (SPEC 4.2 / 7.1)

농가 화면(SPEC 4.2)이 필요로 하는 "농가 한 곳의 지금 상태" 와, 빠른 기능의
첫 단계인 **작물 등록**.
라우터: `backend/app/routers/farm.py`

시세 예측(5.1) · 도매처 추천(5.2) · 스마트팜(5.5) 은 각자의 엔드포인트가 이미
있으므로 여기서 다시 계산하지 않는다. 이 기능이 채우는 빈칸은 두 개다 —
**농가 단위로 묶은 재배 작물** 과 **출하(shipments) 의 등록·조회**.

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/farms` | 농가 목록 — 재배 중인 작물과 예상 수확량 포함 | `FarmOut[]` |
| GET | `/api/farms/{id}` | 농가 하나 | `FarmOut` |
| GET | `/api/shipments?farm_id=&crop_id=` | 출하 이력 — 출하마다 붙은 거래(SPEC 7.1)까지. 출하 예정일 내림차순 | `ShipmentOut[]` |
| POST | `/api/farms/{id}/shipments` | 작물 등록 — 품목·출하량·출하 예정일·등급 | `ShipmentOut` (201) |

`crops` 는 `smartfarms` 를 농가 단위로 묶은 것이고 **재배구역 번호 순**이다 —
그 첫 줄이 SPEC 4.2 메인 현황의 "현재 작물"(시드에서는 1동 토마토)이다.

등록한 출하는 그대로 SPEC 5.2 도매처 추천
([wholesaler_rec](./wholesaler_rec.md), `POST /api/recommendations/wholesalers`)
의 입력이 되고, 농가가 고른 도매처는 `POST /api/deals` 로 같은 출하에 붙는다.
`ShipmentOut.deals` 는 그 결과를 도매처 이름과 함께 되돌려 준다 — `deals` 원장
자체는 도매처 이름을 들고 있지 않기 때문이다.

없는 농가·품목은 **404**, `qty_kg <= 0` 은 **422**.

```jsonc
// FarmOut
{
  "farm_id": 1, "name": "울퉁불퉁 청년농장", "owner_name": "김농부",
  "region_id": 1, "region_name": "충남 논산시", "parcel_id": 1,
  "total_expected_yield_kg": 1400,
  "crops": [
    { "smartfarm_id": 1, "smartfarm_name": "1동 토마토 재배구역",
      "smartfarm_type": "비닐하우스", "crop_id": 1, "crop_name": "토마토",
      "started_on": "2026-04-10", "expected_yield_kg": 1000 }
  ]
}

// ShipmentIn — POST /api/farms/{id}/shipments 본문
{ "crop_id": 1, "qty_kg": 1000, "ship_date": "2026-08-08", "grade": "special" }

// ShipmentOut
{
  "shipment_id": 5, "farm_id": 1, "crop_id": 1, "crop_name": "토마토",
  "qty_kg": 1000, "ship_date": "2026-08-08",
  "grade": "special", "grade_label": "특상품",
  "deals": [
    { "deal_id": 2, "wholesaler_id": 2, "wholesaler_name": "B 농산물유통",
      "agreed_price_krw": 2580000, "status": "proposed",
      "status_label": "추천 제시", "decided_on": null }
  ]
}
```

`grade` 는 SPEC 5.3 과 같은 값(`special` · `standard` · `offgrade` ·
`near_expiry`)이고, `status` 는 SPEC 7.1 의 `proposed` · `accepted` ·
`rejected` · `settled` 다. `grade_label` · `status_label` 이 화면에 그대로
쓰이는 한국어 표기다.
