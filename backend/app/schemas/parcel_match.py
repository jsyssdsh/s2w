"""유휴농지 탐색·적합도 매칭 스키마 (SPEC 5.6 / 7.3 / 4.4 / 4.5).

점수는 서비스 계층이 계산한 값을 그대로 받고, **반올림은 여기서만** 한다
(docs/ARCHITECTURE.md 5절).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.models import (
    ColdStorageAccess,
    ParcelApplicationStatus,
    ParcelCondition,
    ParcelStatus,
)

SCORE_DIGITS = 4
DISTANCE_DIGITS = 1

Pyeong = Annotated[int, Field(gt=0, description="면적(평)")]
Krw = Annotated[int, Field(gt=0, description="금액(원)")]


# --------------------------------------------------------------------------
# 매칭 (SPEC 5.6)
# --------------------------------------------------------------------------


class ParcelMatchRequest(BaseModel):
    """농가 재배 조건 — SPEC 7.3 "희망작물·용도·임대조건"."""

    crop_id: int = Field(description="희망 작물 id")
    area_min_pyeong: Pyeong = Field(description="희망 최소 면적")
    area_max_pyeong: Pyeong = Field(description="희망 최대 면적")
    budget_krw_per_month: Krw = Field(description="월 임대료 예산")
    region_id: int | None = Field(default=None, description="비우면 전체 지역")
    limit: int | None = Field(default=None, gt=0, description="상위 N건만")
    as_of: date | None = Field(default=None, description="기상 적합도 기준일")

    @model_validator(mode="after")
    def _check_area_range(self) -> "ParcelMatchRequest":
        if self.area_min_pyeong > self.area_max_pyeong:
            raise ValueError("area_min_pyeong 은 area_max_pyeong 보다 클 수 없습니다")
        return self


class AxisScoreOut(BaseModel):
    """평가 축 하나 — 추천 근거를 설명 가능하게 만드는 단위."""

    axis: str
    label: str
    value: str
    score: float
    weight: float
    weighted: float

    @field_serializer("score", "weight", "weighted")
    def _round(self, value: float) -> float:
        return round(value, SCORE_DIGITS)


class NearestWholesalerOut(BaseModel):
    id: int
    name: str
    distance_km: float

    @field_serializer("distance_km")
    def _round(self, value: float) -> float:
        return round(value, DISTANCE_DIGITS)


class ParcelMatchOut(BaseModel):
    rank: int
    parcel_id: int
    name: str
    region_id: int
    region_name: str
    area_pyeong: int
    monthly_rent_krw: int
    water_access: bool
    cold_storage_access: ColdStorageAccess
    soil_grade: str
    status: ParcelStatus
    condition: ParcelCondition
    lat: float
    lon: float
    nearest_wholesaler: NearestWholesalerOut | None
    total_score: float
    axes: list[AxisScoreOut]
    reason: str

    @field_serializer("total_score")
    def _round(self, value: float) -> float:
        return round(value, SCORE_DIGITS)


class ParcelMatchResponse(BaseModel):
    crop_id: int
    crop_name: str
    as_of: date
    #: 축별 가중치 — 응답에 실어야 추천 결과를 재현·설명할 수 있다.
    weights: dict[str, float]
    results: list[ParcelMatchOut]


# --------------------------------------------------------------------------
# 지도 (SPEC 4.4)
# --------------------------------------------------------------------------


class ParcelFeatureProperties(BaseModel):
    id: int
    name: str
    region_id: int
    region_name: str
    area_pyeong: int
    monthly_rent_krw: int
    water_access: bool
    cold_storage_access: ColdStorageAccess
    soil_grade: str
    status: ParcelStatus
    status_label: str
    condition: ParcelCondition
    condition_label: str
    #: 녹/황/적 — SPEC 4.4 지도 상태 색상
    color: Literal["green", "amber", "red"]
    color_hex: str


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    #: GeoJSON 좌표 순서는 [경도, 위도]
    coordinates: tuple[float, float]


class ParcelFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: int
    geometry: PointGeometry
    properties: ParcelFeatureProperties


class ParcelFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ParcelFeature]


class ParcelSummaryOut(BaseModel):
    """SPEC 4.4 요약 지표."""

    region_id: int | None
    region_name: str | None
    total_count: int
    idle_count: int
    operating_count: int
    converted_count: int
    applications_today: int
    ai_recommended_deals: int
    land_utilization_rate: float
    as_of: date

    @field_serializer("land_utilization_rate")
    def _round(self, value: float) -> float:
        return round(value, SCORE_DIGITS)


# --------------------------------------------------------------------------
# 상세 (SPEC 4.5)
# --------------------------------------------------------------------------


class OwnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str | None = None


class FacilityOut(BaseModel):
    kind: str
    name: str
    distance_km: float | None
    note: str

    @field_serializer("distance_km")
    def _round(self, value: float | None) -> float | None:
        return None if value is None else round(value, DISTANCE_DIGITS)


class SmartfarmOut(BaseModel):
    id: int
    name: str
    #: 스마트팜 유형 (비닐하우스 / 유리온실 / 노지)
    type: str
    crop_id: int
    crop_name: str
    started_on: date
    expected_yield_kg: int


class ParcelDetailOut(BaseModel):
    id: int
    name: str
    region_id: int
    region_name: str
    area_pyeong: int
    monthly_rent_krw: int
    soil_grade: str
    water_access: bool
    cold_storage_access: ColdStorageAccess
    cold_storage_label: str
    status: ParcelStatus
    status_label: str
    condition: ParcelCondition
    condition_label: str
    color: Literal["green", "amber", "red"]
    color_hex: str
    lat: float
    lon: float
    owner: OwnerOut | None
    nearby_facilities: list[FacilityOut]
    smartfarms: list[SmartfarmOut]
    #: 지역 기준 활용률 — 운영 중·전환 완료 면적 ÷ 전체 유휴농지 면적
    land_utilization_rate: float
    application_count: int

    @field_serializer("land_utilization_rate")
    def _round(self, value: float) -> float:
        return round(value, SCORE_DIGITS)


# --------------------------------------------------------------------------
# 매칭 신청 (SPEC 7.3)
# --------------------------------------------------------------------------


class ParcelApplicationCreate(BaseModel):
    crop_id: int = Field(description="재배할 작물 id")
    applicant_name: str = Field(min_length=1, max_length=64, description="신청 농가명")
    applicant_id: int | None = Field(default=None, description="가입 사용자 id")
    phone: str | None = Field(default=None, max_length=32)
    lease_months: int = Field(default=12, gt=0, le=120, description="희망 임대 기간(개월)")
    message: str = Field(default="", max_length=255)
    match_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="추천 화면에서 본 적합도 점수"
    )
    applied_on: date | None = Field(default=None, description="신청일 (기본 기준일)")


class ParcelApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parcel_id: int
    crop_id: int
    applicant_id: int | None
    applicant_name: str
    phone: str | None
    lease_months: int
    message: str
    match_score: float | None
    status: ParcelApplicationStatus
    applied_on: date


class ParcelApplicationResponse(BaseModel):
    application: ParcelApplicationOut
    #: 신청 처리 후의 필지 상태 — 화면이 지도를 바로 갱신할 수 있도록 함께 준다.
    parcel_status: ParcelStatus
    parcel_status_label: str
