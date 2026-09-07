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
| _(미구현)_ | | | |

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
| _(미구현)_ | | | |

---

## 공용 스키마

```jsonc
// RegionOut
{ "id": 1, "name": "충남 논산시", "lat": 36.187153, "lon": 127.098769 }

// CropOut
{ "id": 1, "name": "토마토", "unit": "kg" }
```

## 오류 응답

FastAPI 기본 형식을 따른다.

```jsonc
{ "detail": "..." }
```

| 상태 코드 | 의미 |
|---|---|
| 404 | 리소스 없음 |
| 422 | 요청 검증 실패 (Pydantic) |
