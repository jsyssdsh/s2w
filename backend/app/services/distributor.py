"""SPEC 4.3 유통업체 대시보드 — 도매처 관점의 집계.

SPEC 5.2 가 "농가 → 어느 도매처로 보낼까" 를 푼다면, 이 모듈은 그 **반대
방향**을 푼다: 도매처가 화면을 열었을 때 "지금 어느 농가 출하를 사와야
하는가" 다. SPEC 4.3 의 화면 요구가 그대로 세 덩어리로 나뉜다.

1. **AI 추천 농가 리스트** — 아직 임자가 정해지지 않은 출하를 도매처 기준으로
   줄 세운다. SPEC 4.3 "향후 수정 계획" 이 요구하는 농가별 거리 · 공급량 ·
   품질 등급 · 운송비 · 예상 순수익 · 추천 이유를 모두 계산해서 낸다.
2. **거래 요청** — 화면의 "거래 요청 보내기" 가 ``deals`` 에 ``proposed``
   행을 남긴다. SPEC 6·7.1 의 피드백 루프에 그대로 들어가는 신호다.
3. **실시간 시장 분석** — 품목별 가격·수요 등락률. 숫자는 SPEC 5.1 예측
   엔진(:mod:`app.services.price_forecast`)에서 그대로 가져온다. 여기서
   두 번째 예측 모델을 만들지 않는다.

계산 규약은 ARCHITECTURE 5절을 따른다 — 금액은 정수 KRW, 거리는
:func:`app.services.geo.haversine_km`, 반올림은 표현 계층. 벽시계 시간은 쓰지
않고 모든 진입점이 ``as_of: date`` 를 받는다 (ARCHITECTURE 6절).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Crop,
    Deal,
    DealStatus,
    Farm,
    Grade,
    Inventory,
    MarketPrice,
    Region,
    Shipment,
    Wholesaler,
)
from app.seed import ANCHOR_DATE
from app.services import price_forecast
from app.services.buyer_match import GRADE_LABEL
from app.services.geo import haversine_km, transport_cost_krw

# --------------------------------------------------------------------------
# 판단 기준 상수 — 화면에 나가는 숫자를 좌우하는 값은 전부 여기 모아 둔다.
# 아래 로직에는 매직 넘버를 두지 않는다.
# --------------------------------------------------------------------------

#: 기능 코드의 ``as_of`` 기본값은 시드 기준일에 맞춘다 (ARCHITECTURE 6절).
DEFAULT_AS_OF: date = ANCHOR_DATE

#: 추천 리스트가 들여다보는 기간(일). 시드의 양파 출하 4건이 모두 들어온다.
DEFAULT_WINDOW_DAYS = 21

#: 시장 분석 패널이 등락률을 재는 기간(일)과 차트에 실어 보내는 구간(일).
DEFAULT_MARKET_LOOKBACK_DAYS = 7
MARKET_SERIES_DAYS = 14

#: 등락률이 이 폭 안이면 "보합" 으로 본다 (백분율).
MARKET_FLAT_PCT = 2.0

MARKET_TREND_UP = "상승세"
MARKET_TREND_DOWN = "하락세"
MARKET_TREND_FLAT = "보합"

#: 등급별 시세 계수. 도매 시세는 "상품" 기준이므로 등급에 따라 오르내린다.
#: (SPEC 5.3 의 등급 구분을 가격 축으로 옮긴 것)
GRADE_PRICE_FACTOR: dict[Grade, float] = {
    Grade.SPECIAL: 1.10,
    Grade.STANDARD: 1.00,
    Grade.OFFGRADE: 0.75,
    Grade.NEAR_EXPIRY: 0.60,
}

#: 도매처가 남겨야 하는 목표 마진율(예상 판매금액 대비). 권장 거래가는
#: 예상 판매금액에서 수수료 · 운송비 · 이 마진을 뺀 나머지를 매입 가능량으로
#: 나눈 값이다. 즉 **운송비가 비쌀수록 농가에 제시할 수 있는 값이 내려간다.**
TARGET_MARGIN_RATE = 0.12

#: 권장 거래가가 등급 반영 예상 판매단가의 이 비율 밑으로 내려가면 농가가
#: 받아들일 만한 제안이 아니라고 보고 "AI 추천" 에서 뺀다. 거리가 멀어 운송비가
#: 물량 값을 먹어 버리는 조합을 리스트 위쪽에 올리지 않기 위한 하한선이다.
VIABLE_OFFER_RATIO = 0.72

#: 추천 이유에 붙이는 등급 설명 (SPEC 5.3 "주요 상태" 표현을 재사용).
GRADE_REASON: dict[Grade, str] = {
    Grade.SPECIAL: "외관과 크기가 균일한 특상품",
    Grade.STANDARD: "대용량 납품이 가능한 상품",
    Grade.OFFGRADE: "모양은 불규칙하지만 품질은 정상인 규격 외",
    Grade.NEAR_EXPIRY: "판매기한이 임박해 신속한 처리가 필요한",
}

#: 거래를 이미 확정한 상태 — 추천 리스트에서 뺀다.
_SETTLED_STATUSES = (DealStatus.ACCEPTED, DealStatus.SETTLED)

#: 화면의 기본 단가 출처. SPEC 5.1 예측 엔진은 모델 캐시가 비어 있으면 품목당
#: 수십 초를 쓰므로(docs/api/price_forecast.md), 대시보드 첫 그림을 거기에
#: 걸지 않는다. 기본값은 기준일의 **실측 도매 시세**이고, 예측이 필요하면
#: ``use_forecast`` 로 명시해서 켠다 — SPEC 5.2 추천 API 와 같은 규약이다.
PRICE_SOURCE_MARKET = "market"     # 실측 도매 시세
PRICE_SOURCE_FORECAST = "forecast" # SPEC 5.1 예측 시세
PRICE_SOURCE_LIST = "list"         # 시세 이력이 없어 도매처 고시 단가로 대체



class UnknownWholesalerError(LookupError):
    """존재하지 않는 도매처."""


class UnknownShipmentError(LookupError):
    """존재하지 않는 출하."""


class ShipmentUnavailableError(ValueError):
    """이미 다른 도매처와 거래가 확정된 출하."""


class UnknownRegionError(LookupError):
    """존재하지 않는 지역."""


# --------------------------------------------------------------------------
# 결과 타입 — 서비스는 계산값을 그대로 돌려주고 반올림은 표현 계층이 한다.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WholesalerInfo:
    """대시보드가 고를 수 있는 도매처 한 곳."""

    id: int
    name: str
    region_id: int
    region_name: str
    unit_price_krw: int
    capacity_kg: int
    fee_rate: float
    transport_cost_per_km: int
    #: 이 도매처가 들고 있는 재고 로트 수 (SPEC 5.3 판매처 연계 패널의 진입점).
    inventory_lot_count: int


@dataclass(frozen=True)
class FarmRecommendation:
    """AI 추천 농가 리스트 한 줄 (SPEC 4.3).

    SPEC 4.3 "향후 수정 계획" 의 여섯 열이 그대로 필드가 된다 —
    거리 · 공급량 · 품질 등급 · 운송비 · 예상 순수익 · 추천 이유.
    """

    shipment_id: int
    farm_id: int
    farm_name: str
    region_id: int
    region_name: str
    crop_id: int
    crop_name: str
    grade: Grade
    ship_date: date
    qty_kg: int                     # 공급량
    purchasable_kg: int             # 도매처 구매 가능량 안에서 살 수 있는 물량
    unsold_kg: int                  # 구매 가능량을 넘어 남는 물량
    distance_km: float              # 농가별 거리
    transport_cost_krw: int         # 운송비
    market_price_per_kg: int        # 기준 단가 (상품 기준)
    graded_price_per_kg: int        # 등급을 반영한 예상 판매 단가
    recommended_price_per_kg: int   # 권장 거래가
    offer_ratio: float              # 권장 거래가 ÷ 예상 판매단가 (제안 경쟁력)
    purchase_cost_krw: int          # 예상 매입금액
    resale_revenue_krw: int         # 예상 판매금액
    fee_krw: int                    # 수수료
    expected_net_profit_krw: int    # 예상 순수익
    margin_rate: float              # 판매금액 대비 순수익 비율
    price_source: str               # market | forecast | list
    requested: bool                 # 이 도매처가 이미 거래 요청을 보냈는가
    recommended: bool               # AI 추천 대상인가
    reason: str                     # 추천 이유


@dataclass(frozen=True)
class RecommendationSummary:
    """SPEC 4.3 요약 타일 — 공급 가능 건수 / AI 추천 건수 / 예상 금액."""

    supply_count: int
    recommended_count: int
    expected_amount_krw: int        # 추천 건의 예상 매입금액 합계
    expected_net_profit_krw: int    # 추천 건의 예상 순수익 합계
    supply_qty_kg: int
    purchasable_qty_kg: int
    requested_count: int


@dataclass(frozen=True)
class FarmRecommendationResult:
    wholesaler: WholesalerInfo
    as_of: date
    window_end: date
    summary: RecommendationSummary
    rows: list[FarmRecommendation]


@dataclass(frozen=True)
class DealRequest:
    """거래 요청 한 건 (``deals`` 의 ``proposed`` 행)."""

    id: int
    shipment_id: int
    wholesaler_id: int
    wholesaler_name: str
    farm_name: str
    crop_name: str
    qty_kg: int
    agreed_price_krw: int
    unit_price_krw: int
    status: DealStatus
    created: bool


@dataclass(frozen=True)
class MarketPoint:
    """시장 분석 차트의 한 점."""

    date: date
    price_per_kg: int
    volume_kg: int


@dataclass(frozen=True)
class MarketRow:
    """품목 한 개의 가격·수요 등락률 (SPEC 4.3 "실시간 시장 분석")."""

    crop_id: int
    crop_name: str
    unit: str
    price_per_kg: int              # 기준일 시세
    previous_price_per_kg: int     # lookback 일 전 시세
    price_change_pct: float
    volume_kg: int                 # 기준일 거래량 (= 수요의 대리 지표)
    previous_volume_kg: int
    demand_change_pct: float
    trend: str                     # 상승세 · 하락세 · 보합
    series: list[MarketPoint]


@dataclass(frozen=True)
class MarketSnapshot:
    region_id: int
    region_name: str
    as_of: date
    lookback_days: int
    rows: list[MarketRow]


# --------------------------------------------------------------------------
# 조회 헬퍼
# --------------------------------------------------------------------------


def _wholesaler_info(
    wholesaler: Wholesaler, region_name: str, inventory_lot_count: int = 0
) -> WholesalerInfo:
    return WholesalerInfo(
        id=wholesaler.id,
        name=wholesaler.name,
        region_id=wholesaler.region_id,
        region_name=region_name,
        unit_price_krw=wholesaler.unit_price_krw,
        capacity_kg=wholesaler.capacity_kg,
        fee_rate=wholesaler.fee_rate,
        transport_cost_per_km=wholesaler.transport_cost_per_km,
        inventory_lot_count=inventory_lot_count,
    )


def list_wholesalers(session: Session) -> list[WholesalerInfo]:
    """대시보드의 도매처 선택기 — 로그인이 붙기 전까지의 진입점이다."""
    lots = (
        select(Inventory.wholesaler_id, func.count(Inventory.id).label("lots"))
        .group_by(Inventory.wholesaler_id)
        .subquery()
    )
    rows = session.execute(
        select(Wholesaler, Region.name, func.coalesce(lots.c.lots, 0))
        .join(Region, Region.id == Wholesaler.region_id)
        .outerjoin(lots, lots.c.wholesaler_id == Wholesaler.id)
        .order_by(Wholesaler.id)
    ).all()
    return [_wholesaler_info(w, region_name, lot_count) for w, region_name, lot_count in rows]


def _inventory_lot_count(session: Session, wholesaler_id: int) -> int:
    return session.scalar(
        select(func.count(Inventory.id)).where(Inventory.wholesaler_id == wholesaler_id)
    ) or 0


def get_wholesaler(session: Session, wholesaler_id: int) -> Wholesaler | None:
    return session.get(Wholesaler, wholesaler_id)


def get_crop(session: Session, crop_id: int) -> Crop | None:
    return session.get(Crop, crop_id)


def get_region(session: Session, region_id: int) -> Region | None:
    return session.get(Region, region_id)


def default_region_id(session: Session) -> int | None:
    """시장 분석의 기본 지역 — 시세 이력이 있는 첫 지역."""
    return session.scalars(select(Region.id).order_by(Region.id).limit(1)).first()


# --------------------------------------------------------------------------
# 1. AI 추천 농가 리스트
# --------------------------------------------------------------------------


def _market_price_on(
    session: Session, crop_id: int, region_id: int, as_of: date
) -> int | None:
    """기준일 이하의 마지막 실측 도매 시세."""
    return session.scalar(
        select(MarketPrice.price_per_kg)
        .where(
            MarketPrice.crop_id == crop_id,
            MarketPrice.region_id == region_id,
            MarketPrice.date <= as_of,
        )
        .order_by(MarketPrice.date.desc())
        .limit(1)
    )


def _forecast_price_on(
    session: Session, crop_id: int, region_id: int, ship_date: date, as_of: date
) -> int | None:
    """출하일의 **예측** 시세 (SPEC 5.1). 불가능하면 ``None``.

    모델 캐시가 비어 있으면 학습에 수십 초가 걸리므로 기본 경로가 아니다 —
    ``use_forecast`` 를 켠 요청만 여기로 온다.
    """
    horizon = max(1, (ship_date - as_of).days)
    if horizon > price_forecast.MAX_HORIZON_DAYS:
        return None
    try:
        result = price_forecast.price_forecast(
            session,
            crop_id=crop_id,
            region_id=region_id,
            horizon=horizon,
            as_of=as_of,
            actual_days=1,
        )
    except (price_forecast.UnknownTargetError, price_forecast.ForecastRangeError):
        return None

    if ship_date <= as_of:
        for actual in result.actuals:
            if actual.date == as_of:
                return actual.price_per_kg
    for point in result.forecast:
        if point.date == ship_date:
            return point.expected_price_per_kg
    return result.forecast[-1].expected_price_per_kg if result.forecast else None


def _reference_price(
    session: Session,
    crop_id: int,
    region_id: int,
    ship_date: date,
    as_of: date,
    fallback_krw: int,
    use_forecast: bool,
) -> tuple[int, str]:
    """권장 거래가를 세울 기준 단가와 그 출처.

    기본은 기준일의 실측 도매 시세다. ``use_forecast`` 를 켜면 SPEC 5.1 예측
    시세를 쓰고, 예측이 불가능하면 조용히 실측으로 되돌아간다. 시세 이력이
    아예 없으면 도매처 고시 단가를 쓴다 (SPEC 5.2 추천 API 와 같은 규약).
    """
    if use_forecast:
        forecast = _forecast_price_on(session, crop_id, region_id, ship_date, as_of)
        if forecast is not None:
            return forecast, PRICE_SOURCE_FORECAST

    market = _market_price_on(session, crop_id, region_id, as_of)
    if market is not None:
        return market, PRICE_SOURCE_MARKET
    return fallback_krw, PRICE_SOURCE_LIST


@dataclass(frozen=True)
class _Offer:
    """권장 거래가와 그 경쟁력(예상 판매단가 대비 비율)."""

    price_per_kg: int
    ratio: float


def _offer(
    graded_price_per_kg: int, purchasable_kg: int, transport_krw: int, fee_rate: float
) -> _Offer:
    """농가에 제시할 권장 거래가.

    예상 판매금액에서 수수료 · 운송비 · 목표 마진을 뺀 나머지가 농가 몫이다.
    운송비는 물량에 상관없이 한 번 드는 값이라, 값싼 품목이나 먼 농가일수록
    제시할 수 있는 단가가 빠르게 내려간다 — 그것이 이 화면이 보여줘야 하는
    판단이다. 남는 것이 없으면 0원이고, 그런 줄은 추천에서 빠진다.
    """
    if purchasable_kg <= 0 or graded_price_per_kg <= 0:
        return _Offer(price_per_kg=0, ratio=0.0)
    resale = graded_price_per_kg * purchasable_kg
    budget = resale - round(resale * fee_rate) - transport_krw - round(resale * TARGET_MARGIN_RATE)
    price = max(0, budget // purchasable_kg)
    return _Offer(price_per_kg=price, ratio=price / graded_price_per_kg)


def _reason(
    row_grade: Grade,
    crop_name: str,
    qty_kg: int,
    purchasable_kg: int,
    distance_km: float,
    offer_ratio: float,
    net_profit_krw: int,
    recommended: bool,
) -> str:
    """SPEC 4.3 "추천 이유" — 왜 이 줄이 이 순위인지 한국어 한 문장으로."""
    grade_text = GRADE_REASON[row_grade]
    volume_text = f"{crop_name} {qty_kg:,}kg 중 {purchasable_kg:,}kg 매입 가능"
    distance_text = f"거리 {distance_km:.0f}km"
    if not recommended:
        if purchasable_kg <= 0:
            return f"{grade_text} 물량이지만 구매 가능량이 남아 있지 않습니다."
        return (
            f"{grade_text} 물량이나 {distance_text} 운송비를 빼고 나면 권장 거래가가 "
            f"예상 판매단가의 {offer_ratio * 100:.0f}% 까지 내려가 추천에서 제외했습니다."
        )
    return (
        f"{grade_text} 물량, {volume_text}, {distance_text}로 "
        f"예상 순수익 {net_profit_krw:,}원, 권장 거래가는 예상 판매단가의 "
        f"{offer_ratio * 100:.0f}% 수준입니다."
    )


def _available_shipments(
    session: Session,
    crop_id: int | None,
    as_of: date,
    window_end: date,
) -> list[tuple[Shipment, Farm, Crop, Region]]:
    """창 안의 출하 중 아직 거래가 확정되지 않은 것."""
    settled = (
        select(Deal.shipment_id)
        .where(Deal.status.in_(_SETTLED_STATUSES))
        .distinct()
    )
    stmt = (
        select(Shipment, Farm, Crop, Region)
        .join(Farm, Farm.id == Shipment.farm_id)
        .join(Crop, Crop.id == Shipment.crop_id)
        .join(Region, Region.id == Farm.region_id)
        .where(Shipment.ship_date >= as_of)
        .where(Shipment.ship_date <= window_end)
        .where(Shipment.id.not_in(settled))
        .order_by(Shipment.ship_date, Shipment.id)
    )
    if crop_id is not None:
        stmt = stmt.where(Shipment.crop_id == crop_id)
    return [tuple(row) for row in session.execute(stmt).all()]


def _requested_shipment_ids(session: Session, wholesaler_id: int) -> set[int]:
    return set(
        session.scalars(
            select(Deal.shipment_id).where(
                Deal.wholesaler_id == wholesaler_id,
                Deal.status == DealStatus.PROPOSED,
            )
        )
    )


def recommend_farms(
    session: Session,
    wholesaler: Wholesaler,
    *,
    crop_id: int | None = None,
    as_of: date = DEFAULT_AS_OF,
    window_days: int = DEFAULT_WINDOW_DAYS,
    use_forecast: bool = False,
) -> FarmRecommendationResult:
    """도매처 기준으로 매입할 만한 농가 출하를 예상 순수익 순으로 세운다.

    한 줄의 계산은 ARCHITECTURE 5절의 순수익 정의를 도매처 쪽으로 옮긴 것이다::

        매입 가능량 = min(출하량, 도매처 구매 가능량)
        예상 판매단가 = 예상 도매 시세 × 등급 계수
        권장 거래가   = 예상 판매단가 × (1 − 목표 마진율)
        예상 판매금액 = 예상 판매단가 × 매입 가능량
        운송비        = haversine_km(농가 시군구, 도매처) × transport_cost_per_km
        수수료        = 예상 판매금액 × fee_rate
        예상 순수익   = 예상 판매금액 − 수수료 − 매입금액 − 운송비
    """
    window_end = as_of + timedelta(days=window_days)
    region_name_of = {r.id: r.name for r in session.scalars(select(Region))}
    requested = _requested_shipment_ids(session, wholesaler.id)

    rows: list[FarmRecommendation] = []
    for shipment, farm, crop, region in _available_shipments(
        session, crop_id, as_of, window_end
    ):
        distance_km = haversine_km(region.lat, region.lon, wholesaler.lat, wholesaler.lon)
        transport = transport_cost_krw(distance_km, wholesaler.transport_cost_per_km)
        purchasable = min(shipment.qty_kg, wholesaler.capacity_kg)

        market_price, source = _reference_price(
            session,
            crop_id=crop.id,
            region_id=region.id,
            ship_date=shipment.ship_date,
            as_of=as_of,
            fallback_krw=wholesaler.unit_price_krw,
            use_forecast=use_forecast,
        )
        graded_price = round(market_price * GRADE_PRICE_FACTOR[shipment.grade])
        offer = _offer(graded_price, purchasable, transport, wholesaler.fee_rate)

        resale = graded_price * purchasable
        purchase_cost = offer.price_per_kg * purchasable
        fee = round(resale * wholesaler.fee_rate)
        net_profit = resale - fee - purchase_cost - transport
        margin_rate = net_profit / resale if resale else 0.0
        is_recommended = purchasable > 0 and offer.ratio >= VIABLE_OFFER_RATIO

        rows.append(
            FarmRecommendation(
                shipment_id=shipment.id,
                farm_id=farm.id,
                farm_name=farm.name,
                region_id=region.id,
                region_name=region_name_of.get(region.id, region.name),
                crop_id=crop.id,
                crop_name=crop.name,
                grade=shipment.grade,
                ship_date=shipment.ship_date,
                qty_kg=shipment.qty_kg,
                purchasable_kg=purchasable,
                unsold_kg=shipment.qty_kg - purchasable,
                distance_km=distance_km,
                transport_cost_krw=transport,
                market_price_per_kg=market_price,
                graded_price_per_kg=graded_price,
                recommended_price_per_kg=offer.price_per_kg,
                offer_ratio=offer.ratio,
                purchase_cost_krw=purchase_cost,
                resale_revenue_krw=resale,
                fee_krw=fee,
                expected_net_profit_krw=net_profit,
                margin_rate=margin_rate,
                price_source=source,
                requested=shipment.id in requested,
                recommended=is_recommended,
                reason=_reason(
                    shipment.grade,
                    crop.name,
                    shipment.qty_kg,
                    purchasable,
                    distance_km,
                    offer.ratio,
                    net_profit,
                    is_recommended,
                ),
            )
        )

    # 추천 대상이 먼저, 그 안에서 예상 순수익이 큰 순. 동점은 출하일 순.
    rows.sort(key=lambda r: (not r.recommended, -r.expected_net_profit_krw, r.ship_date))

    picked = [r for r in rows if r.recommended]
    summary = RecommendationSummary(
        supply_count=len(rows),
        recommended_count=len(picked),
        expected_amount_krw=sum(r.purchase_cost_krw for r in picked),
        expected_net_profit_krw=sum(r.expected_net_profit_krw for r in picked),
        supply_qty_kg=sum(r.qty_kg for r in rows),
        purchasable_qty_kg=sum(r.purchasable_kg for r in picked),
        requested_count=sum(1 for r in rows if r.requested),
    )

    return FarmRecommendationResult(
        wholesaler=_wholesaler_info(
            wholesaler,
            region_name_of.get(wholesaler.region_id, ""),
            _inventory_lot_count(session, wholesaler.id),
        ),
        as_of=as_of,
        window_end=window_end,
        summary=summary,
        rows=rows,
    )


# --------------------------------------------------------------------------
# 2. 거래 요청 보내기
# --------------------------------------------------------------------------


def request_deal(
    session: Session,
    wholesaler_id: int,
    shipment_id: int,
    *,
    unit_price_krw: int | None = None,
    as_of: date = DEFAULT_AS_OF,
) -> DealRequest:
    """화면의 "거래 요청 보내기" — ``deals`` 에 ``proposed`` 행을 남긴다.

    같은 도매처가 같은 출하에 두 번 요청해도 행이 늘지 않는다 (멱등).
    단가를 주지 않으면 추천 리스트의 권장 거래가를 그대로 쓴다.
    """
    wholesaler = get_wholesaler(session, wholesaler_id)
    if wholesaler is None:
        raise UnknownWholesalerError(str(wholesaler_id))

    row = session.execute(
        select(Shipment, Farm, Crop, Region)
        .join(Farm, Farm.id == Shipment.farm_id)
        .join(Crop, Crop.id == Shipment.crop_id)
        .join(Region, Region.id == Farm.region_id)
        .where(Shipment.id == shipment_id)
    ).first()
    if row is None:
        raise UnknownShipmentError(str(shipment_id))
    shipment, farm, crop, region = row

    settled = session.scalars(
        select(Deal).where(
            Deal.shipment_id == shipment_id,
            Deal.status.in_(_SETTLED_STATUSES),
        )
    ).first()
    if settled is not None:
        raise ShipmentUnavailableError(str(shipment_id))

    purchasable = min(shipment.qty_kg, wholesaler.capacity_kg)
    if unit_price_krw is None:
        market_price, _source = _reference_price(
            session,
            crop_id=crop.id,
            region_id=region.id,
            ship_date=shipment.ship_date,
            as_of=as_of,
            fallback_krw=wholesaler.unit_price_krw,
            use_forecast=False,
        )
        graded = round(market_price * GRADE_PRICE_FACTOR[shipment.grade])
        distance_km = haversine_km(
            region.lat, region.lon, wholesaler.lat, wholesaler.lon
        )
        transport = transport_cost_krw(distance_km, wholesaler.transport_cost_per_km)
        unit_price_krw = _offer(
            graded, purchasable, transport, wholesaler.fee_rate
        ).price_per_kg
    agreed = unit_price_krw * purchasable

    existing = session.scalars(
        select(Deal).where(
            Deal.shipment_id == shipment_id,
            Deal.wholesaler_id == wholesaler_id,
            Deal.status == DealStatus.PROPOSED,
        )
    ).first()
    created = existing is None
    if existing is None:
        deal = Deal(
            shipment_id=shipment_id,
            wholesaler_id=wholesaler_id,
            agreed_price_krw=agreed,
            status=DealStatus.PROPOSED,
            decided_on=None,
        )
        session.add(deal)
    else:
        deal = existing
        deal.agreed_price_krw = agreed
    session.commit()

    return DealRequest(
        id=deal.id,
        shipment_id=shipment_id,
        wholesaler_id=wholesaler_id,
        wholesaler_name=wholesaler.name,
        farm_name=farm.name,
        crop_name=crop.name,
        qty_kg=purchasable,
        agreed_price_krw=agreed,
        unit_price_krw=unit_price_krw,
        status=deal.status,
        created=created,
    )


# --------------------------------------------------------------------------
# 3. 실시간 시장 분석
# --------------------------------------------------------------------------


def _change_pct(current: float, expected: float) -> float:
    if not current:
        return 0.0
    return (expected - current) / current * 100.0


def market_snapshot(
    session: Session,
    region_id: int,
    *,
    as_of: date | None = None,
    lookback_days: int = DEFAULT_MARKET_LOOKBACK_DAYS,
    series_days: int = MARKET_SERIES_DAYS,
) -> MarketSnapshot:
    """품목별 가격·수요 등락률 (SPEC 4.3 "실시간 시장 분석").

    숫자는 ``market_prices`` 의 **실측 시세**에서 온다 — 기준일 값과
    ``lookback_days`` 일 전 값을 견줘 등락률을 낸다. 수요는 같은 표의 거래량을
    대리 지표로 쓴다.

    SPEC 5.1 **예측** 엔진을 여기서 부르지 않는 이유는 비용이다. 모델 캐시가
    비어 있으면 품목 하나를 학습하는 데만 수십 초가 걸리고(컨테이너 실측
    ~32초), 품목 다섯이면 대시보드 첫 그림이 몇 분을 기다린다. 예측은 그것을
    감당할 화면(SPEC 4.2 시세 그래프)이 ``GET /api/forecast/price`` 로 직접
    쓰고, 이 패널은 "지금 시장이 어떻게 움직이고 있는가" 를 맡는다.

    시세 이력이 없는 품목은 조용히 건너뛴다 — 화면은 있는 품목만 보여주면 된다.
    """
    region = get_region(session, region_id)
    if region is None:
        raise UnknownRegionError(str(region_id))

    origin = as_of or _latest_price_date(session, region.id)
    if origin is None:
        return MarketSnapshot(
            region_id=region.id,
            region_name=region.name,
            as_of=DEFAULT_AS_OF,
            lookback_days=lookback_days,
            rows=[],
        )

    window_start = origin - timedelta(days=series_days - 1)
    previous_on = origin - timedelta(days=lookback_days)

    rows: list[MarketRow] = []
    for crop in session.scalars(select(Crop).order_by(Crop.id)):
        history = list(
            session.scalars(
                select(MarketPrice)
                .where(
                    MarketPrice.crop_id == crop.id,
                    MarketPrice.region_id == region.id,
                    MarketPrice.date <= origin,
                )
                .order_by(MarketPrice.date)
            )
        )
        if not history:
            continue

        latest = history[-1]
        # lookback 일 전 이하의 마지막 관측 — 그 날 시세가 비어 있어도 이어진다.
        earlier = next(
            (row for row in reversed(history) if row.date <= previous_on), history[0]
        )
        change_pct = _change_pct(earlier.price_per_kg, latest.price_per_kg)
        rows.append(
            MarketRow(
                crop_id=crop.id,
                crop_name=crop.name,
                unit=crop.unit,
                price_per_kg=latest.price_per_kg,
                previous_price_per_kg=earlier.price_per_kg,
                price_change_pct=change_pct,
                volume_kg=latest.volume_kg,
                previous_volume_kg=earlier.volume_kg,
                demand_change_pct=_change_pct(earlier.volume_kg, latest.volume_kg),
                trend=market_trend(change_pct),
                series=[
                    MarketPoint(
                        date=row.date,
                        price_per_kg=row.price_per_kg,
                        volume_kg=row.volume_kg,
                    )
                    for row in history
                    if row.date >= window_start
                ],
            )
        )

    return MarketSnapshot(
        region_id=region.id,
        region_name=region.name,
        as_of=origin,
        lookback_days=lookback_days,
        rows=rows,
    )


def market_trend(change_pct: float) -> str:
    """등락률을 SPEC 4.3 표의 "시장 상황" 한 단어로."""
    if change_pct > MARKET_FLAT_PCT:
        return MARKET_TREND_UP
    if change_pct < -MARKET_FLAT_PCT:
        return MARKET_TREND_DOWN
    return MARKET_TREND_FLAT


def _latest_price_date(session: Session, region_id: int) -> date | None:
    return session.scalar(
        select(func.max(MarketPrice.date)).where(MarketPrice.region_id == region_id)
    )


__all__ = [
    "DEFAULT_AS_OF",
    "DEFAULT_MARKET_LOOKBACK_DAYS",
    "DEFAULT_WINDOW_DAYS",
    "GRADE_LABEL",
    "GRADE_PRICE_FACTOR",
    "VIABLE_OFFER_RATIO",
    "TARGET_MARGIN_RATE",
    "DealRequest",
    "FarmRecommendation",
    "FarmRecommendationResult",
    "MarketPoint",
    "MarketRow",
    "MarketSnapshot",
    "RecommendationSummary",
    "ShipmentUnavailableError",
    "UnknownRegionError",
    "UnknownShipmentError",
    "UnknownWholesalerError",
    "WholesalerInfo",
    "list_wholesalers",
    "market_snapshot",
    "market_trend",
    "recommend_farms",
    "request_deal",
]
