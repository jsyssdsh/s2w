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
| _(미구현)_ | | | |

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
