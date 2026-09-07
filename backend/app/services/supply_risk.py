"""지역별 수급 위험 조기 알림 + 대응 방안 (SPEC 5.4).

SPEC 5.4 의 워크드 예제(양파)를 그대로 계산해 낸다::

    농가 출하 예정량 120톤 + 도매처 기존 재고량 8톤 = 전체 공급량 128톤
    전체 공급량 128톤 − 판매처 구매 수요량 100톤 = 예상 초과 공급량 28톤
    → 위험 단계 "위험", 초과 28톤에 대한 대응 방안 배분

계산 규칙 두 가지를 미리 밝혀 둔다.

1. **지역 수급권.** 시군구 경계와 실제 유통 반경은 다르다. 출하(공급의 생산
   쪽)는 그 지역에 등록된 농가로 한정하지만, 도매처 재고와 판매처 수요는 지역
   중심에서 :data:`SUPPLY_CATCHMENT_KM` 안에 있는 곳까지 묶어 본다. 거리는
   PostGIS 대체물인 :func:`app.services.geo.haversine_km` 를 거친다.
2. **결정론.** 벽시계 시간을 쓰지 않는다. 기준일은 ``as_of`` 파라미터로 받고
   기본값은 시드의 ``ANCHOR_DATE`` 다 (docs/ARCHITECTURE.md 6절).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Buyer,
    BuyerType,
    Crop,
    Demand,
    Farm,
    Inventory,
    Region,
    Shipment,
    Wholesaler,
)
from app.seed import ANCHOR_DATE
from app.services.geo import haversine_km

# --------------------------------------------------------------------------
# 판단 기준 상수 — SPEC 5.4 의 임계값을 한 블록에 모아 둔다.
# 숫자를 바꾸는 곳은 여기뿐이고, 아래 로직에는 매직 넘버를 두지 않는다.
# --------------------------------------------------------------------------

#: 창을 지정하지 않았을 때 들여다보는 기간(일). 시드의 양파 수요 기간
#: (ANCHOR_DATE ~ +21일) 과 같은 길이다.
DEFAULT_WINDOW_DAYS = 21

#: 지역 수급권 반경(km). 지역 중심에서 이 거리 안의 도매처·판매처를 그 지역의
#: 수급권으로 본다. 논산 기준으로 인접 시군(부여·공주·계룡·금산·익산)이 모두
#: 들어오는 값이다.
SUPPLY_CATCHMENT_KM = 50.0

#: 위험 단계 경계 — 초과 공급 비율 = 예상 초과 공급량 ÷ 전체 공급량.
#:   비율 < 5%          → 안정
#:   5% ≤ 비율 < 15%    → 주의
#:   15% ≤ 비율         → 위험
#: SPEC 5.4 양파 예제는 28 / 128 = 21.9% 이므로 "위험" 으로 떨어진다.
RISK_WATCH_RATIO = 0.05
RISK_DANGER_RATIO = 0.15

#: 출하 시기 조정: 창 종료일로부터 이 일수 안에 잡힌 출하만 창 밖으로 미룰 수
#: 있다고 본다. 창 앞쪽 출하를 미루면 보관 기간이 지나치게 길어진다.
SHIPPING_SHIFT_TAIL_DAYS = 7

#: 출하 연기는 물량을 없애는 것이 아니라 다음 기간으로 넘기는 것이다. 다음
#: 기간의 수급을 다시 무너뜨리지 않도록, 창 내 출하 예정량의 이 비율까지만
#: 연기 가능 물량으로 인정한다.
SHIPPING_SHIFT_MAX_SHARE = 0.05


class RiskTier(StrEnum):
    """SPEC 5.4 "위험 단계" 열. 값이 그대로 화면에 나가는 한국어 라벨이다."""

    STABLE = "안정"
    WATCH = "주의"
    DANGER = "위험"


class MitigationChannel(StrEnum):
    """SPEC 5.4 "초과 물량 대응 방안" 네 가지."""

    PROCESSOR = "processor"
    SCHOOL_MEAL = "school_meal"
    SHIPPING_SHIFT = "shipping_shift"
    LOCAL_JOINT = "local_joint"


CHANNEL_LABELS: dict[MitigationChannel, str] = {
    MitigationChannel.PROCESSOR: "식품가공업체 추가 연결",
    MitigationChannel.SCHOOL_MEAL: "학교급식 업체 추가 연결",
    MitigationChannel.SHIPPING_SHIFT: "출하 시기 조정",
    MitigationChannel.LOCAL_JOINT: "지역 공동판매 연계",
}

#: 판매처 연결 채널이 각각 어떤 판매처 유형을 흡수 창구로 쓰는지.
CHANNEL_BUYER_TYPES: dict[MitigationChannel, tuple[BuyerType, ...]] = {
    MitigationChannel.PROCESSOR: (BuyerType.PROCESSOR,),
    MitigationChannel.SCHOOL_MEAL: (BuyerType.SCHOOL_MEAL,),
    MitigationChannel.LOCAL_JOINT: (
        BuyerType.MART,
        BuyerType.RESTAURANT,
        BuyerType.LOCALFOOD,
    ),
}

#: 판매처 추가 연결로 흡수할 수 있는 물량 = 그 판매처가 이 기간에 이미 등록한
#: 수요 × 아래 계수. 등록 수요가 없는 곳은 표준 단위기간 구매량
#: (``buyers.demand_kg``) 에 같은 계수를 적용한다.
#:   가공업체  — 저장·가공으로 소화하므로 여력이 가장 크다
#:   학교급식  — 식단이 미리 확정되어 증량 여지가 제한적이다
#:   지역 공동판매(마트·음식점·로컬푸드) — 소량 분산이라 여력이 작다
CHANNEL_UPLIFT: dict[MitigationChannel, float] = {
    MitigationChannel.PROCESSOR: 0.80,
    MitigationChannel.SCHOOL_MEAL: 0.30,
    MitigationChannel.LOCAL_JOINT: 0.20,
}

#: 배분 우선순위 = SPEC 5.4 표의 순서. 실제 판매로 이어지는 채널을 먼저 채우고,
#: 그다음 출하 연기(문제를 미루는 임시책), 마지막이 단가가 가장 낮은 지역
#: 공동판매다.
CHANNEL_ORDER: tuple[MitigationChannel, ...] = (
    MitigationChannel.PROCESSOR,
    MitigationChannel.SCHOOL_MEAL,
    MitigationChannel.SHIPPING_SHIFT,
    MitigationChannel.LOCAL_JOINT,
)


class UnknownRegionError(LookupError):
    """지역 id 가 없을 때."""


class UnknownCropError(LookupError):
    """품목 id 가 없을 때."""


class InvalidWindowError(ValueError):
    """window_end 가 window_start 보다 앞설 때."""


# --------------------------------------------------------------------------
# 결과 자료구조
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalysisWindow:
    start: date
    end: date


@dataclass(frozen=True)
class VolumeBreakdown:
    """SPEC 5.4 "소급 분석 결과" 표 그대로의 물량 내역 (kg)."""

    farm_shipment_kg: int          # 농가 출하 예정량
    wholesaler_inventory_kg: int   # 도매처 기존 재고량
    buyer_demand_kg: int           # 판매처 구매 수요량

    @property
    def total_supply_kg(self) -> int:
        """전체 공급량 = 농가 출하 예정량 + 도매처 기존 재고량."""
        return self.farm_shipment_kg + self.wholesaler_inventory_kg

    @property
    def excess_supply_kg(self) -> int:
        """예상 초과 공급량 = 전체 공급량 − 판매처 구매 수요량.

        음수면 공급 부족(수요가 더 많음)이라는 뜻이며, 그대로 돌려준다.
        """
        return self.total_supply_kg - self.buyer_demand_kg


@dataclass(frozen=True)
class MitigationAction:
    """대응 방안 한 줄 — 채널, 배정 물량, 그 채널이 감당 가능한 상한."""

    channel: MitigationChannel
    label: str
    qty_kg: int
    capacity_kg: int
    detail: str

    @property
    def headroom_kg(self) -> int:
        """이 채널에 아직 남아 있는 여력."""
        return self.capacity_kg - self.qty_kg


@dataclass(frozen=True)
class MitigationPlan:
    """네 채널에 대한 배분 결과.

    ``planned_kg`` + ``shortfall_kg`` == 초과 공급량 이 항상 성립한다. 여력이
    모자라면 숫자를 맞추지 않고 ``shortfall_kg`` 로 드러낸다.
    """

    actions: list[MitigationAction]
    #: 이 계획이 처리해야 하는 물량 = max(0, 예상 초과 공급량). 공급 부족(초과가
    #: 음수)이면 0 이고, 대응 방안도 전부 0 이다.
    target_kg: int

    @property
    def planned_kg(self) -> int:
        return sum(a.qty_kg for a in self.actions)

    @property
    def shortfall_kg(self) -> int:
        """여력이 모자라 어느 채널로도 보내지 못한 물량."""
        return self.target_kg - self.planned_kg

    @property
    def is_fully_covered(self) -> bool:
        return self.shortfall_kg <= 0


@dataclass(frozen=True)
class SupplyRiskAssessment:
    region: Region
    crop: Crop
    window: AnalysisWindow
    volumes: VolumeBreakdown
    excess_ratio: float
    risk_tier: RiskTier
    mitigation: MitigationPlan

    @property
    def headline(self) -> str:
        """대시보드 알림 한 줄 (SPEC 4.3 유통업체 대시보드)."""
        tons = self.volumes.excess_supply_kg / 1000
        return (
            f"{self.region.name} {self.crop.name} 예상 초과 공급 {tons:,.1f}톤 "
            f"— {self.risk_tier.value}"
        )


# --------------------------------------------------------------------------
# 수급권 조회
# --------------------------------------------------------------------------


def _load_region(session: Session, region_id: int) -> Region:
    region = session.get(Region, region_id)
    if region is None:
        raise UnknownRegionError(f"region_id={region_id}")
    return region


def _load_crop(session: Session, crop_id: int) -> Crop:
    crop = session.get(Crop, crop_id)
    if crop is None:
        raise UnknownCropError(f"crop_id={crop_id}")
    return crop


def catchment_wholesalers(session: Session, region: Region) -> list[Wholesaler]:
    """지역 중심에서 :data:`SUPPLY_CATCHMENT_KM` 안의 도매처."""
    return [
        w
        for w in session.scalars(select(Wholesaler).order_by(Wholesaler.id))
        if haversine_km(region.lat, region.lon, w.lat, w.lon) <= SUPPLY_CATCHMENT_KM
    ]


def catchment_buyers(session: Session, region: Region) -> list[Buyer]:
    """지역 중심에서 :data:`SUPPLY_CATCHMENT_KM` 안의 판매처."""
    return [
        b
        for b in session.scalars(select(Buyer).order_by(Buyer.id))
        if haversine_km(region.lat, region.lon, b.lat, b.lon) <= SUPPLY_CATCHMENT_KM
    ]


def registered_demand_by_buyer(
    session: Session, crop: Crop, buyer_ids: list[int], window: AnalysisWindow
) -> dict[int, int]:
    """창과 겹치는 기간을 가진 판매처별 등록 수요 합계 (kg)."""
    if not buyer_ids:
        return {}
    rows = session.execute(
        select(Demand.buyer_id, func.sum(Demand.qty_kg))
        .where(
            Demand.crop_id == crop.id,
            Demand.buyer_id.in_(buyer_ids),
            # 기간이 조금이라도 겹치면 이 창의 수요로 센다.
            Demand.period_start <= window.end,
            Demand.period_end >= window.start,
        )
        .group_by(Demand.buyer_id)
    ).all()
    return {buyer_id: int(qty or 0) for buyer_id, qty in rows}


def _farm_shipment_kg(
    session: Session, region: Region, crop: Crop, window: AnalysisWindow
) -> int:
    """창 안에 출하가 예정된, 이 지역 농가의 물량 합계 (kg)."""
    total = session.scalar(
        select(func.coalesce(func.sum(Shipment.qty_kg), 0))
        .join(Farm, Farm.id == Shipment.farm_id)
        .where(
            Farm.region_id == region.id,
            Shipment.crop_id == crop.id,
            Shipment.ship_date >= window.start,
            Shipment.ship_date <= window.end,
        )
    )
    return int(total or 0)


def _wholesaler_inventory_kg(
    session: Session, wholesaler_ids: list[int], crop: Crop, window: AnalysisWindow
) -> int:
    """수급권 도매처가 창 시작 시점에 들고 있는 재고 (kg).

    창이 시작되기 전에 유통기한이 끝나는 재고는 이 창의 공급이 아니다.
    """
    if not wholesaler_ids:
        return 0
    total = session.scalar(
        select(func.coalesce(func.sum(Inventory.qty_kg), 0)).where(
            Inventory.wholesaler_id.in_(wholesaler_ids),
            Inventory.crop_id == crop.id,
            or_(Inventory.expiry_date.is_(None), Inventory.expiry_date >= window.start),
        )
    )
    return int(total or 0)


def shiftable_shipment_kg(
    session: Session, region: Region, crop: Crop, window: AnalysisWindow
) -> int:
    """출하 시기 조정으로 창 밖으로 미룰 수 있는 물량 (kg).

    출하일이 창 종료일에 가까울수록 조금만 미뤄도 창을 벗어나므로 보관 부담이
    작다. 그래서 ``window.end`` 기준 :data:`SHIPPING_SHIFT_TAIL_DAYS` 이내의
    출하만 후보로 본다.

    SPEC 5.1 의 출하 시기(shipping-window) 서비스가 들어오면 여기가 그 서비스를
    호출하는 단 한 곳이 된다 — 그때는 "며칠 미루면 시세가 어떻게 되는가" 까지
    함께 판단하게 된다.
    """
    cutoff = window.end - timedelta(days=SHIPPING_SHIFT_TAIL_DAYS)
    total = session.scalar(
        select(func.coalesce(func.sum(Shipment.qty_kg), 0))
        .join(Farm, Farm.id == Shipment.farm_id)
        .where(
            Farm.region_id == region.id,
            Shipment.crop_id == crop.id,
            Shipment.ship_date >= cutoff,
            Shipment.ship_date <= window.end,
        )
    )
    return int(total or 0)


# --------------------------------------------------------------------------
# 위험 단계 · 대응 방안
# --------------------------------------------------------------------------


def excess_ratio(volumes: VolumeBreakdown) -> float:
    """초과 공급 비율 = 예상 초과 공급량 ÷ 전체 공급량.

    공급이 0 이면 비교할 대상이 없으므로 0.0 이다.
    """
    if volumes.total_supply_kg <= 0:
        return 0.0
    return volumes.excess_supply_kg / volumes.total_supply_kg


def risk_tier(ratio: float) -> RiskTier:
    """초과 공급 비율 → 위험 단계 (:data:`RISK_WATCH_RATIO` 블록 참고)."""
    if ratio >= RISK_DANGER_RATIO:
        return RiskTier.DANGER
    if ratio >= RISK_WATCH_RATIO:
        return RiskTier.WATCH
    return RiskTier.STABLE


def _buyer_channel_capacity(
    channel: MitigationChannel,
    buyers: list[Buyer],
    registered: dict[int, int],
) -> tuple[int, int]:
    """(추가 흡수 여력 kg, 대상 판매처 수).

    이미 이 창에 수요를 등록한 곳은 등록 수요를, 등록이 없는 곳은 표준 단위기간
    구매량(``buyers.demand_kg``)을 기준으로 계수를 곱한다. 후자가 SPEC 이 말하는
    "추가 연결" — 아직 이 품목을 사지 않는 판매처를 새로 붙이는 경우다.
    """
    uplift = CHANNEL_UPLIFT[channel]
    targets = [b for b in buyers if b.type in CHANNEL_BUYER_TYPES[channel]]
    capacity = 0
    for buyer in targets:
        base = registered.get(buyer.id) or buyer.demand_kg
        # kg 는 정수다. 내림해서 없는 여력을 만들어 내지 않는다.
        capacity += int(base * uplift)
    return capacity, len(targets)


def plan_mitigation(
    session: Session,
    region: Region,
    crop: Crop,
    window: AnalysisWindow,
    excess_supply_kg: int,
    buyers: list[Buyer],
    registered: dict[int, int],
    window_shipment_kg: int,
) -> MitigationPlan:
    """초과 물량을 네 채널에 우선순위대로 배분한다.

    각 채널은 실제 여력(``capacity_kg``) 이상을 받지 않으며, 배분 합계는 초과
    공급량을 넘지 않는다. 여력이 모자라면 남는 물량은
    :attr:`MitigationPlan.shortfall_kg` 로 그대로 노출한다 — 숫자를 맞추려고
    없는 여력을 지어내지 않는다.
    """
    excess = max(0, excess_supply_kg)

    capacities: dict[MitigationChannel, int] = {}
    details: dict[MitigationChannel, str] = {}

    for channel in (
        MitigationChannel.PROCESSOR,
        MitigationChannel.SCHOOL_MEAL,
        MitigationChannel.LOCAL_JOINT,
    ):
        capacity, count = _buyer_channel_capacity(channel, buyers, registered)
        capacities[channel] = capacity
        details[channel] = (
            f"수급권 내 대상 판매처 {count}곳, 등록 수요 대비 "
            f"{CHANNEL_UPLIFT[channel]:.0%} 증량 여력"
        )

    shiftable = shiftable_shipment_kg(session, region, crop, window)
    share_cap = int(window_shipment_kg * SHIPPING_SHIFT_MAX_SHARE)
    capacities[MitigationChannel.SHIPPING_SHIFT] = min(shiftable, share_cap)
    details[MitigationChannel.SHIPPING_SHIFT] = (
        f"창 종료 {SHIPPING_SHIFT_TAIL_DAYS}일 이내 출하 {shiftable:,}kg 중 "
        f"창 내 출하량의 {SHIPPING_SHIFT_MAX_SHARE:.0%}({share_cap:,}kg)까지 연기"
    )

    actions: list[MitigationAction] = []
    remaining = excess
    for channel in CHANNEL_ORDER:
        capacity = max(0, capacities[channel])
        qty = min(capacity, remaining)
        remaining -= qty
        actions.append(
            MitigationAction(
                channel=channel,
                label=CHANNEL_LABELS[channel],
                qty_kg=qty,
                capacity_kg=capacity,
                detail=details[channel],
            )
        )

    return MitigationPlan(actions=actions, target_kg=excess)


# --------------------------------------------------------------------------
# 공개 진입점
# --------------------------------------------------------------------------


def resolve_window(
    window_start: date | None = None,
    window_end: date | None = None,
    as_of: date | None = None,
) -> AnalysisWindow:
    """창을 확정한다. 비어 있으면 ``as_of`` 부터 기본 기간만큼."""
    start = window_start or as_of or ANCHOR_DATE
    end = window_end or start + timedelta(days=DEFAULT_WINDOW_DAYS)
    if end < start:
        raise InvalidWindowError(f"window_end={end} < window_start={start}")
    return AnalysisWindow(start=start, end=end)


def assess_region_crop(
    session: Session,
    region: Region,
    crop: Crop,
    window: AnalysisWindow,
) -> SupplyRiskAssessment:
    """한 지역·한 품목의 수급 위험과 대응 방안 (SPEC 5.4 전체)."""
    wholesaler_ids = [w.id for w in catchment_wholesalers(session, region)]
    buyers = catchment_buyers(session, region)
    registered = registered_demand_by_buyer(
        session, crop, [b.id for b in buyers], window
    )

    shipment_kg = _farm_shipment_kg(session, region, crop, window)
    volumes = VolumeBreakdown(
        farm_shipment_kg=shipment_kg,
        wholesaler_inventory_kg=_wholesaler_inventory_kg(
            session, wholesaler_ids, crop, window
        ),
        buyer_demand_kg=sum(registered.values()),
    )
    ratio = excess_ratio(volumes)

    return SupplyRiskAssessment(
        region=region,
        crop=crop,
        window=window,
        volumes=volumes,
        excess_ratio=ratio,
        risk_tier=risk_tier(ratio),
        mitigation=plan_mitigation(
            session,
            region,
            crop,
            window,
            volumes.excess_supply_kg,
            buyers,
            registered,
            shipment_kg,
        ),
    )


def assess(
    session: Session,
    region_id: int,
    crop_id: int,
    window_start: date | None = None,
    window_end: date | None = None,
    as_of: date | None = None,
) -> SupplyRiskAssessment:
    """``GET /api/supply-risk`` 뒤의 계산 전부."""
    region = _load_region(session, region_id)
    crop = _load_crop(session, crop_id)
    return assess_region_crop(
        session, region, crop, resolve_window(window_start, window_end, as_of)
    )


def active_alerts(
    session: Session,
    region_id: int,
    as_of: date | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[SupplyRiskAssessment]:
    """한 지역의 품목별 활성 위험 알림 — 안정 단계는 뺀다.

    유통업체 대시보드(SPEC 4.3)가 쓰는 목록이라 위험한 순서로 정렬한다.
    """
    region = _load_region(session, region_id)
    start = as_of or ANCHOR_DATE
    window = resolve_window(start, start + timedelta(days=window_days))

    alerts = [
        assessment
        for crop in session.scalars(select(Crop).order_by(Crop.id))
        if (assessment := assess_region_crop(session, region, crop, window)).risk_tier
        is not RiskTier.STABLE
    ]
    alerts.sort(key=lambda a: (a.excess_ratio, a.volumes.excess_supply_kg), reverse=True)
    return alerts
