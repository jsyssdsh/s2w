"""유휴농지 탐색·적합도 매칭 + 지도 데이터 API (SPEC 5.6 / 7.3 / 4.4 / 4.5).

HTTP 계층만 둔다 — 점수 계산과 질의는 ``app/services/parcel_match.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Crop
from app.schemas.parcel_match import (
    AxisScoreOut,
    FacilityOut,
    NearestWholesalerOut,
    OwnerOut,
    ParcelApplicationCreate,
    ParcelApplicationOut,
    ParcelApplicationResponse,
    ParcelDetailOut,
    ParcelFeature,
    ParcelFeatureCollection,
    ParcelFeatureProperties,
    ParcelMatchOut,
    ParcelMatchRequest,
    ParcelMatchResponse,
    ParcelSummaryOut,
    PointGeometry,
    SmartfarmOut,
)
from app.seed import ANCHOR_DATE
from app.services import parcel_match as service

router = APIRouter(prefix="/api/parcels", tags=["parcels"])


@router.post("/match", response_model=ParcelMatchResponse)
def match(
    request: ParcelMatchRequest,
    session: Session = Depends(get_session),
) -> ParcelMatchResponse:
    """희망 작물·면적·예산으로 유휴농지를 순위화한다 (SPEC 5.6)."""
    crop = session.get(Crop, request.crop_id)
    if crop is None:
        raise HTTPException(status_code=404, detail=f"작물 {request.crop_id} 을(를) 찾을 수 없습니다.")

    as_of = request.as_of or ANCHOR_DATE
    matches = service.match_parcels(
        session,
        crop_id=request.crop_id,
        area_min_pyeong=request.area_min_pyeong,
        area_max_pyeong=request.area_max_pyeong,
        budget_krw_per_month=request.budget_krw_per_month,
        region_id=request.region_id,
        limit=request.limit,
        as_of=as_of,
    )

    return ParcelMatchResponse(
        crop_id=crop.id,
        crop_name=crop.name,
        as_of=as_of,
        weights=service.WEIGHTS,
        results=[
            ParcelMatchOut(
                rank=m.rank,
                parcel_id=m.parcel.id,
                name=m.parcel.name,
                region_id=m.region.id,
                region_name=m.region.name,
                area_pyeong=m.parcel.area_pyeong,
                monthly_rent_krw=m.parcel.monthly_rent_krw,
                water_access=m.parcel.water_access,
                cold_storage_access=m.parcel.cold_storage_access,
                soil_grade=m.parcel.soil_grade,
                status=m.parcel.status,
                condition=m.parcel.condition,
                lat=m.parcel.lat,
                lon=m.parcel.lon,
                nearest_wholesaler=(
                    None
                    if m.nearest_wholesaler is None
                    else NearestWholesalerOut(
                        id=m.nearest_wholesaler.id,
                        name=m.nearest_wholesaler.name,
                        distance_km=m.distance_km,
                    )
                ),
                total_score=m.total_score,
                axes=[
                    AxisScoreOut(
                        axis=a.axis,
                        label=a.label,
                        value=a.value,
                        score=a.score,
                        weight=a.weight,
                        weighted=a.weighted,
                    )
                    for a in m.axes
                ],
                reason=m.reason,
            )
            for m in matches
        ],
    )


@router.get("/geojson", response_model=ParcelFeatureCollection)
def geojson(
    region_id: int | None = Query(default=None, description="비우면 전체 지역"),
    session: Session = Depends(get_session),
) -> ParcelFeatureCollection:
    """SPEC 4.4 지도용 GeoJSON. 색상은 condition 에서 나온다 (녹/황/적)."""
    features = []
    for parcel, region in service.list_parcels(session, region_id):
        condition_label, color, color_hex = service.condition_style(parcel.condition)
        features.append(
            ParcelFeature(
                id=parcel.id,
                geometry=PointGeometry(coordinates=(parcel.lon, parcel.lat)),
                properties=ParcelFeatureProperties(
                    id=parcel.id,
                    name=parcel.name,
                    region_id=region.id,
                    region_name=region.name,
                    area_pyeong=parcel.area_pyeong,
                    monthly_rent_krw=parcel.monthly_rent_krw,
                    water_access=parcel.water_access,
                    cold_storage_access=parcel.cold_storage_access,
                    soil_grade=parcel.soil_grade,
                    status=parcel.status,
                    status_label=service.STATUS_LABELS[parcel.status],
                    condition=parcel.condition,
                    condition_label=condition_label,
                    color=color,
                    color_hex=color_hex,
                ),
            )
        )
    return ParcelFeatureCollection(features=features)


@router.get("/summary", response_model=ParcelSummaryOut)
def summary(
    region_id: int | None = Query(default=None, description="비우면 전체 지역"),
    session: Session = Depends(get_session),
) -> ParcelSummaryOut:
    """SPEC 4.4 요약 지표: 운영 중 / 전환 완료 / 오늘 신청량 / AI 추천 거래."""
    result = service.summary(session, region_id)
    return ParcelSummaryOut(
        region_id=result.region_id,
        region_name=result.region_name,
        total_count=result.total_count,
        idle_count=result.idle_count,
        operating_count=result.operating_count,
        converted_count=result.converted_count,
        applications_today=result.applications_today,
        ai_recommended_deals=result.ai_recommended_deals,
        land_utilization_rate=result.land_utilization_rate,
        as_of=result.as_of,
    )


@router.get("/{parcel_id}", response_model=ParcelDetailOut)
def detail(parcel_id: int, session: Session = Depends(get_session)) -> ParcelDetailOut:
    """SPEC 4.5 유휴토지 상세."""
    found = service.parcel_detail(session, parcel_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"농지 {parcel_id} 을(를) 찾을 수 없습니다.")

    parcel = found.parcel
    condition_label, color, color_hex = service.condition_style(parcel.condition)
    return ParcelDetailOut(
        id=parcel.id,
        name=parcel.name,
        region_id=found.region.id,
        region_name=found.region.name,
        area_pyeong=parcel.area_pyeong,
        monthly_rent_krw=parcel.monthly_rent_krw,
        soil_grade=parcel.soil_grade,
        water_access=parcel.water_access,
        cold_storage_access=parcel.cold_storage_access,
        cold_storage_label=service.COLD_STORAGE_LABELS[parcel.cold_storage_access],
        status=parcel.status,
        status_label=service.STATUS_LABELS[parcel.status],
        condition=parcel.condition,
        condition_label=condition_label,
        color=color,
        color_hex=color_hex,
        lat=parcel.lat,
        lon=parcel.lon,
        owner=None if found.owner is None else OwnerOut.model_validate(found.owner),
        nearby_facilities=[
            FacilityOut(
                kind=f.kind, name=f.name, distance_km=f.distance_km, note=f.note
            )
            for f in found.facilities
        ],
        smartfarms=[
            SmartfarmOut(
                id=smartfarm.id,
                name=smartfarm.name,
                type=smartfarm.type,
                crop_id=crop.id,
                crop_name=crop.name,
                started_on=smartfarm.started_on,
                expected_yield_kg=smartfarm.expected_yield_kg,
            )
            for smartfarm, crop in found.smartfarms
        ],
        land_utilization_rate=found.land_utilization_rate,
        application_count=found.application_count,
    )


@router.post(
    "/{parcel_id}/applications",
    response_model=ParcelApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply(
    parcel_id: int,
    body: ParcelApplicationCreate,
    session: Session = Depends(get_session),
) -> ParcelApplicationResponse:
    """SPEC 7.3 매칭 신청. 접수되면 필지는 유휴 → 운영 중으로 넘어간다."""
    try:
        application = service.create_application(
            session,
            parcel_id=parcel_id,
            crop_id=body.crop_id,
            applicant_name=body.applicant_name,
            applicant_id=body.applicant_id,
            phone=body.phone,
            lease_months=body.lease_months,
            message=body.message,
            match_score=body.match_score,
            applied_on=body.applied_on or ANCHOR_DATE,
        )
    except service.ApplicationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if application is None:
        raise HTTPException(status_code=404, detail=f"농지 {parcel_id} 을(를) 찾을 수 없습니다.")

    parcel_status = application.parcel.status
    return ParcelApplicationResponse(
        application=ParcelApplicationOut.model_validate(application),
        parcel_status=parcel_status,
        parcel_status_label=service.STATUS_LABELS[parcel_status],
    )
