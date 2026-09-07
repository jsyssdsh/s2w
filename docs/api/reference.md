# 참조 데이터 (SPEC 6)

지역·품목 등 모든 기능이 공유하는 조회용 데이터.
라우터: `backend/app/routers/reference.py`

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/regions` | 시군구 목록 | `RegionOut[]` |
| GET | `/api/crops` | 품목 목록 | `CropOut[]` |

`RegionOut` · `CropOut` 는 여러 기능이 함께 쓰므로
[API.md 의 공용 스키마](../API.md#공용-스키마) 에 둔다.
