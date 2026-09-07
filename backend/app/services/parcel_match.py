"""유휴농지 적합도 매칭과 지도 데이터 — SPEC 5.6 / 7.3 / 4.4 / 4.5.

SPEC 7.3 의 흐름(토지 소유자의 유휴농지 정보 × 농가의 희망 조건 → 적합도
점수 → 추천 → 매칭 신청)을 그대로 구현한다. 점수는 **설명 가능해야 한다**:
축별 점수·가중치·근거 문장을 그대로 돌려주므로 SPEC 4.4 의 "조건 비교" 화면이
추천 이유를 보여줄 수 있다.

가중치는 아래 한 블록에만 있다. 다른 곳에서 숫자를 다시 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ColdStorageAccess,
    Crop,
    CropThreshold,
    Deal,
    Farm,
    Parcel,
    ParcelApplication,
    ParcelApplicationStatus,
    ParcelCondition,
    ParcelStatus,
    Region,
    Shipment,
    Smartfarm,
    User,
    UserRole,
    WeatherDaily,
    Wholesaler,
)
from app.seed import ANCHOR_DATE
from app.services.geo import haversine_km

# --------------------------------------------------------------------------
# 평가 축과 가중치 (SPEC 5.6 평가 항목)
#
# 합계 1.0. 농업용수는 SPEC 표에서 C 농지가 가장 짧은 도매처 거리(17km)를
# 가지고도 3위로 밀리는 이유이므로, 다른 어떤 축보다 무겁게 둔다 — 용수가
# 없으면 나머지를 아무리 잘 받아도 순위를 되찾지 못한다.
# --------------------------------------------------------------------------

WEIGHT_WATER = 0.30           # 농업용수 확보 여부
WEIGHT_CROP = 0.20            # 작물 적합도 (기상 + 토양)
WEIGHT_AREA = 0.15            # 희망 면적 적합도
WEIGHT_RENT = 0.15            # 월 임대료 대비 예산
WEIGHT_DISTANCE = 0.12        # 도매처까지의 거리
WEIGHT_COLD_STORAGE = 0.08    # 냉장창고 접근성

WEIGHTS: dict[str, float] = {
    "water": WEIGHT_WATER,
    "crop": WEIGHT_CROP,
    "area": WEIGHT_AREA,
    "rent": WEIGHT_RENT,
    "distance": WEIGHT_DISTANCE,
    "cold_storage": WEIGHT_COLD_STORAGE,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "가중치 합은 1.0 이어야 한다"

AXIS_LABELS: dict[str, str] = {
    "water": "농업용수",
    "crop": "작물 적합도",
    "area": "면적",
    "rent": "월 임대료",
    "distance": "도매처 거리",
    "cold_storage": "냉장창고 접근성",
}

#: 거리 점수가 0 이 되는 지점. 충남 논산 기준 도매처 권역의 바깥 경계다.
DISTANCE_HORIZON_KM = 60.0

#: 작물 적합도 = 기상 적합도 × 0.6 + 토양 등급 × 0.4
CROP_WEATHER_SHARE = 0.6
CROP_SOIL_SHARE = 0.4

#: 기상 적합도를 계산할 창(일). 계절을 한 바퀴 돌아야 편향이 없다.
WEATHER_WINDOW_DAYS = 365

SOIL_GRADE_SCORE: dict[str, float] = {"1등급": 1.0, "2등급": 0.7, "3등급": 0.4}
SOIL_GRADE_FALLBACK = 0.5

COLD_STORAGE_SCORE: dict[ColdStorageAccess, float] = {
    ColdStorageAccess.POSSIBLE: 1.0,
    ColdStorageAccess.LIMITED: 0.5,
    ColdStorageAccess.NONE: 0.0,
}
COLD_STORAGE_LABELS: dict[ColdStorageAccess, str] = {
    ColdStorageAccess.POSSIBLE: "가능",
    ColdStorageAccess.LIMITED: "제한적",
    ColdStorageAccess.NONE: "미확보",
}

STATUS_LABELS: dict[ParcelStatus, str] = {
    ParcelStatus.IDLE: "유휴",
    ParcelStatus.OPERATING: "운영 중",
    ParcelStatus.CONVERTED: "전환 완료",
}

#: SPEC 4.4 지도 색상 구분: 상태 최상(녹) / 상태 양호(황) / 개선 필요(적)
CONDITION_STYLE: dict[ParcelCondition, tuple[str, str, str]] = {
    # condition -> (한국어 라벨, 색상 클래스, 색상 코드)
    ParcelCondition.BEST: ("상태 최상", "green", "#16a34a"),
    ParcelCondition.GOOD: ("상태 양호", "amber", "#f59e0b"),
    ParcelCondition.NEEDS_IMPROVEMENT: ("개선 필요", "red", "#dc2626"),
}

#: 활용 중으로 세는 상태 (SPEC 4.4 운영 중 / 전환 완료)
IN_USE_STATUSES = (ParcelStatus.OPERATING, ParcelStatus.CONVERTED)


# --------------------------------------------------------------------------
# 결과 자료구조
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AxisScore:
    """축 하나의 점수 — 추천 근거를 그대로 노출하기 위한 단위."""

    axis: str
    label: str
    value: str          # 사람이 읽는 원시 값 ("900평", "확보", "24.0km")
    score: float        # 0.0–1.0
    weight: float

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass(frozen=True)
class ParcelMatch:
    parcel: Parcel
    region: Region
    rank: int
    total_score: float
    axes: list[AxisScore]
    distance_km: float
    nearest_wholesaler: Wholesaler | None
    reason: str


@dataclass(frozen=True)
class Facility:
    kind: str
    name: str
    distance_km: float | None
    note: str


@dataclass(frozen=True)
class ParcelDetail:
    parcel: Parcel
    region: Region
    owner: User | None
    smartfarms: list[tuple[Smartfarm, Crop]]
    facilities: list[Facility]
    land_utilization_rate: float
    application_count: int


@dataclass(frozen=True)
class ParcelSummary:
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


# --------------------------------------------------------------------------
# 축별 점수 함수 — 전부 0.0–1.0
# --------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def area_score(area_pyeong: int, area_min: int, area_max: int) -> float:
    """희망 범위 안이면 만점, 벗어나면 벗어난 비율만큼 깎는다."""
    if area_min <= area_pyeong <= area_max:
        return 1.0
    if area_pyeong < area_min:
        return _clamp01(1.0 - (area_min - area_pyeong) / area_min)
    return _clamp01(1.0 - (area_pyeong - area_max) / area_max)


def rent_score(monthly_rent_krw: int, budget_krw_per_month: int) -> float:
    """예산 대비 임대료. 예산을 넘으면 0 — 실제 영농에 못 쓰는 조건이다."""
    if budget_krw_per_month <= 0:
        return 0.0
    return _clamp01(1.0 - monthly_rent_krw / budget_krw_per_month)


def distance_score(distance_km: float | None) -> float:
    """도매처가 가까울수록 높다. ``DISTANCE_HORIZON_KM`` 밖이면 0."""
    if distance_km is None:
        return 0.0
    return _clamp01(1.0 - distance_km / DISTANCE_HORIZON_KM)


def soil_score(soil_grade: str) -> float:
    return SOIL_GRADE_SCORE.get(soil_grade, SOIL_GRADE_FALLBACK)


def crop_score(weather_fit: float, soil_grade: str) -> float:
    """기상 적합일 비율과 토양 등급을 합친 작물 적합도."""
    return (
        CROP_WEATHER_SHARE * _clamp01(weather_fit)
        + CROP_SOIL_SHARE * soil_score(soil_grade)
    )


# --------------------------------------------------------------------------
# 조회 헬퍼
# --------------------------------------------------------------------------


def _krw(value: int) -> str:
    """65만 원 / 650,000원 — SPEC 표기에 맞춘 금액 문자열."""
    if value >= 10_000 and value % 10_000 == 0:
        return f"{value // 10_000}만 원"
    return f"{value:,}원"


def nearest_wholesaler(
    parcel: Parcel, wholesalers: list[Wholesaler]
) -> tuple[Wholesaler | None, float | None]:
    """가장 가까운 도매처와 거리(km). 거리는 항상 ``geo.haversine_km`` 을 쓴다."""
    if not wholesalers:
        return None, None
    return min(
        (
            (w, haversine_km(parcel.lat, parcel.lon, w.lat, w.lon))
            for w in wholesalers
        ),
        key=lambda pair: pair[1],
    )


def weather_fit_by_region(
    session: Session,
    threshold: CropThreshold | None,
    as_of: date,
) -> dict[int, float]:
    """지역별 '작물 적정 온도에 들어온 날' 비율.

    기준이 없는 작물은 중립값 0.5 로 본다.
    """
    rows = session.execute(
        select(WeatherDaily.region_id, WeatherDaily.temp_avg).where(
            WeatherDaily.date > as_of - timedelta(days=WEATHER_WINDOW_DAYS),
            WeatherDaily.date <= as_of,
        )
    ).all()

    totals: dict[int, int] = {}
    hits: dict[int, int] = {}
    for region_id, temp_avg in rows:
        totals[region_id] = totals.get(region_id, 0) + 1
        if threshold is not None and threshold.temp_min <= temp_avg <= threshold.temp_max:
            hits[region_id] = hits.get(region_id, 0) + 1

    if threshold is None:
        return {region_id: 0.5 for region_id in totals}
    return {
        region_id: hits.get(region_id, 0) / total
        for region_id, total in totals.items()
        if total
    }


# --------------------------------------------------------------------------
# SPEC 5.6 — 적합도 매칭
# --------------------------------------------------------------------------


def _reason(
    parcel: Parcel,
    axes: dict[str, AxisScore],
    *,
    area_min: int,
    area_max: int,
    budget_krw_per_month: int,
    distance_km: float | None,
    wholesaler: Wholesaler | None,
) -> str:
    """축 점수를 한국어 근거 문장으로 — SPEC 4.4 "추천 이유"."""
    strengths: list[str] = []
    weaknesses: list[str] = []

    if parcel.water_access:
        strengths.append("농업용수 확보")

    area_range = f"희망 범위({area_min:,}~{area_max:,}평)"
    if axes["area"].score >= 1.0:
        strengths.append(f"면적 {parcel.area_pyeong:,}평으로 {area_range} 충족")
    else:
        weaknesses.append(f"면적 {parcel.area_pyeong:,}평으로 {area_range}를 벗어남")

    rent = _krw(parcel.monthly_rent_krw)
    budget = _krw(budget_krw_per_month)
    if axes["rent"].score > 0.0:
        strengths.append(f"월 임대료 {rent}으로 예산 {budget} 이내")
    elif parcel.monthly_rent_krw > budget_krw_per_month:
        weaknesses.append(f"월 임대료 {rent}으로 예산 {budget} 초과")
    else:
        weaknesses.append(f"월 임대료 {rent}으로 예산 {budget} 대비 여유 없음")

    if distance_km is not None and wholesaler is not None:
        where = f"도매처({wholesaler.name})까지 {distance_km:.1f}km"
        if axes["distance"].score >= 0.5:
            strengths.append(where)
        else:
            weaknesses.append(f"{where}로 원거리")

    cold = COLD_STORAGE_LABELS[parcel.cold_storage_access]
    if parcel.cold_storage_access is ColdStorageAccess.POSSIBLE:
        strengths.append(f"냉장창고 접근 {cold}")
    else:
        weaknesses.append(f"냉장창고 접근성 {cold}")

    sentences: list[str] = []
    if strengths:
        sentences.append(f"{', '.join(strengths)} 항목이 우수합니다.")
    if weaknesses:
        prefix = "다만 " if strengths else ""
        sentences.append(f"{prefix}{', '.join(weaknesses)} 항목은 불리합니다.")
    if not parcel.water_access:
        # SPEC 5.6 에서 C 농지를 3위로 밀어내는 결정적 사유.
        sentences.append("특히 농업용수가 확보되지 않아 적합도가 크게 낮습니다.")
    return " ".join(sentences)


def match_parcels(
    session: Session,
    *,
    crop_id: int,
    area_min_pyeong: int,
    area_max_pyeong: int,
    budget_krw_per_month: int,
    region_id: int | None = None,
    limit: int | None = None,
    as_of: date = ANCHOR_DATE,
) -> list[ParcelMatch]:
    """희망 작물·면적·예산을 물류 조건과 비교해 농지를 순위화한다 (SPEC 5.6).

    SPEC 5.6 비교표는 세 농지를 상태와 무관하게 나란히 세우므로, 여기서도
    필지 상태로 거르지 않는다. 상태는 결과에 실려 나가고, 실제 신청 가능
    여부는 :func:`create_application` 이 판단한다.
    """
    stmt = select(Parcel)
    if region_id is not None:
        stmt = stmt.where(Parcel.region_id == region_id)
    parcels = list(session.scalars(stmt.order_by(Parcel.id)))
    if not parcels:
        return []

    wholesalers = list(session.scalars(select(Wholesaler)))
    regions = {r.id: r for r in session.scalars(select(Region))}
    threshold = session.scalars(
        select(CropThreshold).where(CropThreshold.crop_id == crop_id)
    ).one_or_none()
    weather = weather_fit_by_region(session, threshold, as_of)

    scored: list[tuple[float, Parcel, dict[str, AxisScore], float | None, Wholesaler | None]] = []
    for parcel in parcels:
        wholesaler, distance_km = nearest_wholesaler(parcel, wholesalers)
        fit = weather.get(parcel.region_id, 0.5)

        axes = {
            "water": AxisScore(
                "water",
                AXIS_LABELS["water"],
                "확보" if parcel.water_access else "미확보",
                1.0 if parcel.water_access else 0.0,
                WEIGHT_WATER,
            ),
            "crop": AxisScore(
                "crop",
                AXIS_LABELS["crop"],
                f"기상 적합일 {fit * 100:.0f}% · 토양 {parcel.soil_grade}",
                crop_score(fit, parcel.soil_grade),
                WEIGHT_CROP,
            ),
            "area": AxisScore(
                "area",
                AXIS_LABELS["area"],
                f"{parcel.area_pyeong:,}평",
                area_score(parcel.area_pyeong, area_min_pyeong, area_max_pyeong),
                WEIGHT_AREA,
            ),
            "rent": AxisScore(
                "rent",
                AXIS_LABELS["rent"],
                _krw(parcel.monthly_rent_krw),
                rent_score(parcel.monthly_rent_krw, budget_krw_per_month),
                WEIGHT_RENT,
            ),
            "distance": AxisScore(
                "distance",
                AXIS_LABELS["distance"],
                "-" if distance_km is None else f"{distance_km:.1f}km",
                distance_score(distance_km),
                WEIGHT_DISTANCE,
            ),
            "cold_storage": AxisScore(
                "cold_storage",
                AXIS_LABELS["cold_storage"],
                COLD_STORAGE_LABELS[parcel.cold_storage_access],
                COLD_STORAGE_SCORE[parcel.cold_storage_access],
                WEIGHT_COLD_STORAGE,
            ),
        }
        total = sum(axis.weighted for axis in axes.values())
        scored.append((total, parcel, axes, distance_km, wholesaler))

    # 동점이면 임대료가 싼 쪽, 그래도 같으면 id 순 — 결정론적 순서.
    scored.sort(key=lambda row: (-row[0], row[1].monthly_rent_krw, row[1].id))

    matches = [
        ParcelMatch(
            parcel=parcel,
            region=regions[parcel.region_id],
            rank=index,
            total_score=total,
            axes=list(axes.values()),
            distance_km=distance_km if distance_km is not None else 0.0,
            nearest_wholesaler=wholesaler,
            reason=_reason(
                parcel,
                axes,
                area_min=area_min_pyeong,
                area_max=area_max_pyeong,
                budget_krw_per_month=budget_krw_per_month,
                distance_km=distance_km,
                wholesaler=wholesaler,
            ),
        )
        for index, (total, parcel, axes, distance_km, wholesaler) in enumerate(scored, start=1)
    ]
    return matches[:limit] if limit else matches


# --------------------------------------------------------------------------
# SPEC 7.3 — 유휴농지 등록 (토지 소유자)
# --------------------------------------------------------------------------


class RegistrationError(Exception):
    """같은 지역에 같은 이름의 농지가 이미 있다 — 라우터가 409 로 옮긴다."""


def create_parcel(
    session: Session,
    *,
    name: str,
    region_id: int,
    area_pyeong: int,
    monthly_rent_krw: int,
    water_access: bool = False,
    cold_storage_access: ColdStorageAccess = ColdStorageAccess.NONE,
    soil_grade: str = "3등급",
    lat: float | None = None,
    lon: float | None = None,
    condition: ParcelCondition = ParcelCondition.GOOD,
    owner_name: str | None = None,
    owner_phone: str | None = None,
) -> tuple[Parcel, Region] | None:
    """SPEC 7.3 첫 단계 — 토지 소유자가 유휴농지 발생을 등록한다.

    좌표를 주지 않으면 시군구 중심을 쓴다. 소유자 이름을 주면
    ``landowner`` 사용자를 함께 만들어 SPEC 4.5 상세 화면의 연락처를 채운다.
    상태는 언제나 ``idle`` 이다 — 운영 중으로 넘기는 것은 매칭 신청뿐이다.
    """
    region = session.get(Region, region_id)
    if region is None:
        return None  # 없는 지역 — 라우터가 404 로 옮긴다

    clash = session.scalar(
        select(Parcel).where(Parcel.region_id == region_id, Parcel.name == name)
    )
    if clash is not None:
        raise RegistrationError(
            f"{region.name} 에는 이미 '{name}' 이(가) 등록돼 있습니다."
        )

    owner_id = None
    if owner_name:
        owner = User(
            name=owner_name,
            role=UserRole.LANDOWNER,
            phone=owner_phone,
            region_id=region_id,
        )
        session.add(owner)
        session.flush()
        owner_id = owner.id

    parcel = Parcel(
        name=name,
        region_id=region_id,
        owner_id=owner_id,
        area_pyeong=area_pyeong,
        monthly_rent_krw=monthly_rent_krw,
        water_access=water_access,
        cold_storage_access=cold_storage_access,
        soil_grade=soil_grade,
        lat=region.lat if lat is None else lat,
        lon=region.lon if lon is None else lon,
        status=ParcelStatus.IDLE,
        condition=condition,
    )
    session.add(parcel)
    session.commit()
    session.refresh(parcel)
    return parcel, region


# --------------------------------------------------------------------------
# SPEC 4.4 — 지도 데이터와 요약 지표
# --------------------------------------------------------------------------


def list_parcels(session: Session, region_id: int | None = None) -> list[tuple[Parcel, Region]]:
    stmt = select(Parcel, Region).join(Region, Parcel.region_id == Region.id)
    if region_id is not None:
        stmt = stmt.where(Parcel.region_id == region_id)
    return [tuple(row) for row in session.execute(stmt.order_by(Parcel.id)).all()]


def condition_style(condition: ParcelCondition) -> tuple[str, str, str]:
    """(라벨, 색상 클래스, 색상 코드) — SPEC 4.4 녹/황/적."""
    return CONDITION_STYLE[condition]


def land_utilization_rate(session: Session, region_id: int | None = None) -> float:
    """활용 중(운영 중·전환 완료) 농지 면적 ÷ 전체 유휴농지 면적."""
    stmt = select(Parcel.status, func.sum(Parcel.area_pyeong))
    if region_id is not None:
        stmt = stmt.where(Parcel.region_id == region_id)
    rows = session.execute(stmt.group_by(Parcel.status)).all()
    total = sum(area or 0 for _, area in rows)
    if not total:
        return 0.0
    in_use = sum(area or 0 for status, area in rows if status in IN_USE_STATUSES)
    return in_use / total


def summary(
    session: Session,
    region_id: int | None = None,
    as_of: date = ANCHOR_DATE,
) -> ParcelSummary:
    """SPEC 4.4 요약 지표: 운영 중 / 전환 완료 / 오늘 신청량 / AI 추천 거래."""
    counts_stmt = select(Parcel.status, func.count(Parcel.id))
    if region_id is not None:
        counts_stmt = counts_stmt.where(Parcel.region_id == region_id)
    counts = {status: count for status, count in session.execute(counts_stmt.group_by(Parcel.status))}

    applications_stmt = (
        select(func.count(ParcelApplication.id))
        .join(Parcel, ParcelApplication.parcel_id == Parcel.id)
        .where(ParcelApplication.applied_on == as_of)
    )
    deals_stmt = (
        select(func.count(Deal.id))
        .join(Shipment, Deal.shipment_id == Shipment.id)
        .join(Farm, Shipment.farm_id == Farm.id)
    )
    if region_id is not None:
        applications_stmt = applications_stmt.where(Parcel.region_id == region_id)
        deals_stmt = deals_stmt.where(Farm.region_id == region_id)

    region = session.get(Region, region_id) if region_id is not None else None
    return ParcelSummary(
        region_id=region_id,
        region_name=region.name if region else None,
        total_count=sum(counts.values()),
        idle_count=counts.get(ParcelStatus.IDLE, 0),
        operating_count=counts.get(ParcelStatus.OPERATING, 0),
        converted_count=counts.get(ParcelStatus.CONVERTED, 0),
        applications_today=session.scalar(applications_stmt) or 0,
        ai_recommended_deals=session.scalar(deals_stmt) or 0,
        land_utilization_rate=land_utilization_rate(session, region_id),
        as_of=as_of,
    )


# --------------------------------------------------------------------------
# SPEC 4.5 — 유휴토지 상세
# --------------------------------------------------------------------------


def parcel_detail(session: Session, parcel_id: int) -> ParcelDetail | None:
    parcel = session.get(Parcel, parcel_id)
    if parcel is None:
        return None

    region = session.get(Region, parcel.region_id)
    owner = session.get(User, parcel.owner_id) if parcel.owner_id else None

    smartfarms = [
        (smartfarm, crop)
        for smartfarm, crop in session.execute(
            select(Smartfarm, Crop)
            .join(Crop, Smartfarm.crop_id == Crop.id)
            .where(Smartfarm.parcel_id == parcel.id)
            .order_by(Smartfarm.id)
        ).all()
    ]

    # 주변 시설: 도매처(거리순 3곳) + 냉장창고 접근성
    wholesalers = sorted(
        (
            (haversine_km(parcel.lat, parcel.lon, w.lat, w.lon), w)
            for w in session.scalars(select(Wholesaler))
        ),
        key=lambda pair: pair[0],
    )[:3]
    facilities = [
        Facility(
            kind="wholesaler",
            name=w.name,
            distance_km=km,
            note=f"매입단가 {w.unit_price_krw:,}원/kg",
        )
        for km, w in wholesalers
    ]
    facilities.append(
        Facility(
            kind="cold_storage",
            name="냉장창고",
            distance_km=None,
            note=COLD_STORAGE_LABELS[parcel.cold_storage_access],
        )
    )

    application_count = session.scalar(
        select(func.count(ParcelApplication.id)).where(
            ParcelApplication.parcel_id == parcel.id
        )
    ) or 0

    return ParcelDetail(
        parcel=parcel,
        region=region,
        owner=owner,
        smartfarms=smartfarms,
        facilities=facilities,
        land_utilization_rate=land_utilization_rate(session, parcel.region_id),
        application_count=application_count,
    )


# --------------------------------------------------------------------------
# SPEC 7.3 — 매칭 신청
# --------------------------------------------------------------------------


class ApplicationError(Exception):
    """신청을 받을 수 없는 상태 — 라우터가 409 로 옮긴다."""


def create_application(
    session: Session,
    *,
    parcel_id: int,
    crop_id: int,
    applicant_name: str,
    applicant_id: int | None = None,
    phone: str | None = None,
    lease_months: int = 12,
    message: str = "",
    match_score: float | None = None,
    applied_on: date = ANCHOR_DATE,
) -> ParcelApplication | None:
    """임대(매칭) 신청을 저장하고 필지 상태를 넘긴다.

    ``idle`` 필지만 신청을 받는다. 접수되면 필지는 ``operating`` 으로 바뀌어
    지도(SPEC 4.4)에서 더 이상 유휴로 보이지 않는다.
    """
    parcel = session.get(Parcel, parcel_id)
    if parcel is None:
        return None  # 없는 필지 — 라우터가 404 로 옮긴다
    if parcel.status is not ParcelStatus.IDLE:
        raise ApplicationError(
            f"'{parcel.name}'은(는) 현재 {STATUS_LABELS[parcel.status]} 상태라 신청할 수 없습니다."
        )
    if session.get(Crop, crop_id) is None:
        raise ApplicationError(f"작물 {crop_id} 을(를) 찾을 수 없습니다.")

    application = ParcelApplication(
        parcel_id=parcel.id,
        crop_id=crop_id,
        applicant_id=applicant_id,
        applicant_name=applicant_name,
        phone=phone,
        lease_months=lease_months,
        message=message,
        match_score=match_score,
        status=ParcelApplicationStatus.PENDING,
        applied_on=applied_on,
    )
    session.add(application)
    parcel.status = ParcelStatus.OPERATING
    session.commit()
    session.refresh(application)
    return application
