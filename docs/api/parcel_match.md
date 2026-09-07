# 유휴농지 탐색·적합도 매칭 (SPEC 5.6 / 7.3)

라우터: `backend/app/routers/parcel_match.py` ·
서비스: `backend/app/services/parcel_match.py` ·
스키마: `backend/app/schemas/parcel_match.py`

## 엔드포인트

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| POST | `/api/parcels` | 유휴농지 등록 (SPEC 7.3 토지 소유자) — 언제나 `idle` 로 생성 | `ParcelFeature` (201) |
| POST | `/api/parcels/match` | 희망 작물·면적·예산으로 유휴농지 적합도 순위 산출 | `ParcelMatchResponse` |
| GET | `/api/parcels/geojson?region_id=` | 지도용 GeoJSON (SPEC 4.4, 상태 색상 포함) | `ParcelFeatureCollection` |
| GET | `/api/parcels/summary?region_id=` | 요약 지표 — 운영 중 / 전환 완료 / 오늘 신청량 / AI 추천 거래 (SPEC 4.4) | `ParcelSummaryOut` |
| GET | `/api/parcels/{id}` | 유휴토지 상세 (SPEC 4.5) | `ParcelDetailOut` |
| POST | `/api/parcels/{id}/applications` | 임대(매칭) 신청 — 필지를 `idle` → `operating` 으로 전환 (SPEC 7.3) | `ParcelApplicationResponse` (201) |

### 유휴농지 등록 (SPEC 7.3)

SPEC 7.3 흐름의 첫 단계 — "토지 소유자(유휴농지 발생 등록)". 응답은 지도가
그대로 쓰는 `ParcelFeature` 라, 등록 직후 화면이 새 마커를 바로 그릴 수 있다.

```jsonc
// POST /api/parcels 요청
{
  "name": "E 시험농지",
  "region_id": 1,
  "area_pyeong": 2400,
  "monthly_rent_krw": 1200000,
  "water_access": false,            // 기본 false
  "cold_storage_access": "none",    // possible | limited | none (기본 none)
  "soil_grade": "3등급",             // 기본 "3등급"
  "lat": null,                      // 생략하면 시군구 중심
  "lon": null,
  "condition": "good",              // best | good | needs_improvement (기본 good)
  "owner_name": "최소유",            // 있으면 landowner 사용자를 함께 만든다
  "owner_phone": "010-1000-0009"
}
```

- **상태는 요청으로 정할 수 없다.** 등록은 언제나 `idle` 이고, 필지를
  `operating` 으로 넘기는 것은 매칭 신청(`POST /api/parcels/{id}/applications`)
  하나뿐이다. 그래야 지도가 "등록됐지만 아직 아무도 안 쓰는 땅" 을 정확히 센다.
- **좌표는 선택이다.** 토지 소유자가 위경도를 알 이유가 없어서, 비우면 시군구
  중심을 넣는다. 거리 축(도매처 거리)은 그 좌표로 계산된다.
- `owner_name` 을 주면 `landowner` 역할의 사용자를 만들어 SPEC 4.5 상세의
  연락처를 채운다. 비우면 상세의 `owner` 가 `null` 이다.

없는 `region_id` 는 **404**, 같은 지역에 같은 이름이 이미 있으면 **409**
(지도 라벨이 겹치면 어느 땅을 고른 것인지 알 수 없다), 나머지 검증 실패는
**422** 다.

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

## 스키마

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
