"""농가 맞춤형 도매처 추천 (SPEC 5.2) 과 거래 피드백 루프 (SPEC 6 / 7.1).

핵심은 SPEC 6.2 의 한 줄이다::

    예상 순수익 = 판매금액 − 운송비 − 수수료

세 항목 모두 도매처마다 다르기 때문에 **매입단가가 가장 높은 도매처가 이기지
않는다.** SPEC 5.2 의 C 도매처가 그 예다: 단가는 2,700원/kg 으로 가장 높지만
구매 가능량이 800kg 뿐이라 1,000kg 중 200kg 을 팔지 못하고, 거리도 멀어 3위로
내려간다.

거래 피드백 루프(SPEC 7.1 "실제 거래 결과는 다음 추천에 반영한다")는 도매처별
**이행률(reliability)** 로 구현했다. ``deals`` 에 남은 결론난 거래 중 실제로
이행된(accepted/settled) 비율을 구해, 예상 순수익을 최대 ``RELIABILITY_WEIGHT``
만큼 할인한 값으로 정렬한다. 자세한 규칙은 ``reliability_scores`` 참고.

숫자 규약은 docs/ARCHITECTURE.md 5절을 따른다. 이 모듈은 계산값을 float 로
그대로 돌려주고, 반올림은 ``app/schemas/wholesaler_rec.py`` (표현 계층) 에서
한다.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Crop, Deal, DealStatus, Farm, Region, Shipment, Wholesaler
from app.services.geo import haversine_km

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 튜닝 상수 — 추천 정책을 바꾸려면 여기만 고친다.
# --------------------------------------------------------------------------

#: 이행 상태로 취급하는 거래 상태.
FULFILLED_STATUSES: tuple[DealStatus, ...] = (DealStatus.ACCEPTED, DealStatus.SETTLED)

#: 결론이 난 거래 상태. ``proposed`` 는 아직 농가가 선택하지 않았을 뿐이므로
#: 이행 실패로 세지 않는다 — 세면 추천을 많이 받은 도매처가 벌점을 받는다.
DECIDED_STATUSES: tuple[DealStatus, ...] = (
    DealStatus.ACCEPTED,
    DealStatus.SETTLED,
    DealStatus.REJECTED,
)

#: 신뢰도 사전확률. 거래 이력이 없는 도매처가 불리해지지 않도록 "이미 이행한
#: 가상 거래 RELIABILITY_PRIOR_STRENGTH 건" 을 깔고 시작한다. 이력이 쌓일수록
#: 사전확률의 영향은 자연히 줄어든다.
RELIABILITY_PRIOR_STRENGTH = 4.0
RELIABILITY_PRIOR = 1.0

#: 신뢰도가 순위에 미치는 최대 감점 폭. 신뢰도 0 인 도매처는 예상 순수익을
#: 15% 할인한 값으로 정렬한다. 근소한 차이는 뒤집을 수 있지만, 모든 도매처가
#: 중립(1.0)인 SPEC 5.2 기본 시나리오의 순위(B > A > C)는 건드리지 않는다.
RELIABILITY_WEIGHT = 0.15

#: 이 값 미만이면 추천 사유에 경고 문구를 붙인다.
RELIABILITY_WARN_BELOW = 0.9

#: ``use_forecast=True`` 일 때 단가를 가져올 예측 서비스 (SPEC 5.1, s2w-01i).
#: 계약: ``fn(session, *, crop_id, region_id, target_date) -> float`` (원/kg).
#: 아직 없으면 정적 단가로 조용히 되돌아간다 — 두 기능은 병렬로 만들어진다.
FORECAST_PROVIDER: tuple[str, str] = (
    "app.services.price_forecast",
    "forecast_price_per_kg",
)

PRICE_SOURCE_STATIC = "static"
PRICE_SOURCE_FORECAST = "forecast"


class RecommendationError(LookupError):
    """참조하는 행이 없을 때. 라우터가 404 로 옮긴다."""


# --------------------------------------------------------------------------
# 결과 자료구조
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Reliability:
    """도매처별 거래 이행 이력 (SPEC 7.1 피드백 루프)."""

    proposed_total: int
    decided: int
    fulfilled: int
    score: float

    @property
    def raw_rate(self) -> float | None:
        """스무딩 전 이행률. 결론난 거래가 없으면 None."""
        return self.fulfilled / self.decided if self.decided else None


@dataclass(frozen=True)
class Candidate:
    """도매처 한 곳의 예상 순수익 분해."""

    wholesaler_id: int
    name: str
    distance_km: float
    unit_price_krw: int
    #: ``wholesalers.unit_price_krw``. 예측 단가를 쓰면 위 값과 달라진다.
    list_unit_price_krw: int
    capacity_kg: int
    sellable_kg: int
    unsold_kg: int
    gross_krw: float
    transport_cost_krw: float
    fee_rate: float
    fee_krw: float
    net_profit_krw: float
    reliability: Reliability
    #: 신뢰도를 반영한 정렬 기준값. 신뢰도가 중립이면 순수익과 같다.
    ranking_score_krw: float
    rank: int
    reason: str


@dataclass(frozen=True)
class Recommendation:
    farm_id: int
    farm_name: str
    crop_id: int
    crop_name: str
    qty_kg: int
    ship_date: date
    price_source: str
    notes: list[str]
    candidates: list[Candidate]


# --------------------------------------------------------------------------
# 피드백 루프
# --------------------------------------------------------------------------


def reliability_scores(session: Session) -> dict[int, Reliability]:
    """도매처별 이행률.

    ``score`` 는 베이지안 스무딩을 거친 값이다::

        score = (이행 건수 + 4 × 1.0) / (결론난 건수 + 4)

    - 거래 이력이 없으면 1.0 (중립) — 신규 도매처를 벌주지 않는다.
    - 이행 실패가 쌓일수록 0 에 가까워진다.
    - 아직 ``proposed`` 상태인 거래는 분모에 넣지 않는다.
    """
    counted = func.sum(
        case((Deal.status.in_(DECIDED_STATUSES), 1), else_=0)
    ).label("decided")
    fulfilled = func.sum(
        case((Deal.status.in_(FULFILLED_STATUSES), 1), else_=0)
    ).label("fulfilled")
    rows = session.execute(
        select(Deal.wholesaler_id, func.count(Deal.id), counted, fulfilled).group_by(
            Deal.wholesaler_id
        )
    ).all()

    scores: dict[int, Reliability] = {}
    for wholesaler_id, total, decided, done in rows:
        scores[wholesaler_id] = _reliability(int(total), int(decided or 0), int(done or 0))
    return scores


def _reliability(total: int, decided: int, fulfilled: int) -> Reliability:
    score = (fulfilled + RELIABILITY_PRIOR_STRENGTH * RELIABILITY_PRIOR) / (
        decided + RELIABILITY_PRIOR_STRENGTH
    )
    return Reliability(
        proposed_total=total, decided=decided, fulfilled=fulfilled, score=score
    )


NEUTRAL_RELIABILITY = _reliability(0, 0, 0)


# --------------------------------------------------------------------------
# 예측 단가 연동 (SPEC 5.1)
# --------------------------------------------------------------------------


def load_price_forecaster() -> Callable[..., float] | None:
    """``FORECAST_PROVIDER`` 를 늦게 임포트한다. 없으면 None."""
    module_name, attr = FORECAST_PROVIDER
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    provider = getattr(module, attr, None)
    return provider if callable(provider) else None


def _forecast_unit_price(
    session: Session, *, crop_id: int, region_id: int, ship_date: date
) -> int | None:
    provider = load_price_forecaster()
    if provider is None:
        return None
    try:
        price = provider(
            session, crop_id=crop_id, region_id=region_id, target_date=ship_date
        )
    except Exception:  # pragma: no cover - 예측 실패로 추천이 죽으면 안 된다
        logger.exception("price forecast failed; falling back to static unit price")
        return None
    return max(1, round(float(price)))


# --------------------------------------------------------------------------
# 추천
# --------------------------------------------------------------------------


def farm_origin(session: Session, farm: Farm) -> tuple[float, float]:
    """운송비 계산의 출발점.

    ``farms`` 에는 좌표 컬럼이 없으므로 (docs/ARCHITECTURE.md 의 공유 모델)
    소속 시군구의 좌표를 쓴다. 시드가 보장하는 SPEC 5.2 운송비(18/8/21만원)도
    이 기준으로 계산된 값이다.
    """
    region = session.get(Region, farm.region_id)
    if region is None:  # pragma: no cover - FK 가 막아 준다
        raise RecommendationError(f"region {farm.region_id} not found")
    return region.lat, region.lon


def recommend_wholesalers(
    session: Session,
    *,
    farm_id: int,
    crop_id: int,
    qty_kg: int,
    ship_date: date,
    use_forecast: bool = False,
    limit: int | None = None,
) -> Recommendation:
    """도매처별 예상 순수익을 계산해 순위를 매긴다 (SPEC 5.2)."""
    farm = session.get(Farm, farm_id)
    if farm is None:
        raise RecommendationError(f"farm {farm_id} not found")
    crop = session.get(Crop, crop_id)
    if crop is None:
        raise RecommendationError(f"crop {crop_id} not found")

    origin_lat, origin_lon = farm_origin(session, farm)
    wholesalers = list(session.scalars(select(Wholesaler).order_by(Wholesaler.id)))
    scores = reliability_scores(session)

    notes: list[str] = []
    price_source = PRICE_SOURCE_STATIC
    forecast_price: int | None = None
    if use_forecast:
        forecast_price = _forecast_unit_price(
            session, crop_id=crop_id, region_id=farm.region_id, ship_date=ship_date
        )
        if forecast_price is None:
            notes.append(
                "시세 예측 서비스를 사용할 수 없어 도매처 고시 단가로 계산했습니다."
            )
        else:
            price_source = PRICE_SOURCE_FORECAST
            notes.append(
                f"{ship_date:%Y-%m-%d} 예측 시세 {forecast_price:,}원/kg 을 "
                "모든 도매처의 단가로 적용했습니다."
            )

    drafts: list[dict] = []
    for w in wholesalers:
        unit_price = forecast_price if forecast_price is not None else w.unit_price_krw
        sellable = min(qty_kg, w.capacity_kg)
        gross = float(unit_price * sellable)
        distance = haversine_km(origin_lat, origin_lon, w.lat, w.lon)
        transport = distance * w.transport_cost_per_km
        fee = gross * w.fee_rate
        net = gross - transport - fee
        reliability = scores.get(w.id, NEUTRAL_RELIABILITY)
        drafts.append(
            {
                "wholesaler": w,
                "unit_price": unit_price,
                "sellable": sellable,
                "gross": gross,
                "distance": distance,
                "transport": transport,
                "fee": fee,
                "net": net,
                "reliability": reliability,
                "score": net * _reliability_multiplier(reliability.score),
            }
        )

    # 동점이면 순수익이 큰 쪽, 그래도 같으면 id 순 — 정렬을 결정론적으로.
    drafts.sort(key=lambda d: (-d["score"], -d["net"], d["wholesaler"].id))
    best_net = drafts[0]["net"] if drafts else 0.0

    candidates: list[Candidate] = []
    for index, d in enumerate(drafts, start=1):
        w: Wholesaler = d["wholesaler"]
        candidate = Candidate(
            wholesaler_id=w.id,
            name=w.name,
            distance_km=d["distance"],
            unit_price_krw=d["unit_price"],
            list_unit_price_krw=w.unit_price_krw,
            capacity_kg=w.capacity_kg,
            sellable_kg=d["sellable"],
            unsold_kg=qty_kg - d["sellable"],
            gross_krw=d["gross"],
            transport_cost_krw=d["transport"],
            fee_rate=w.fee_rate,
            fee_krw=d["fee"],
            net_profit_krw=d["net"],
            reliability=d["reliability"],
            ranking_score_krw=d["score"],
            rank=index,
            reason="",
        )
        candidates.append(
            _with_reason(candidate, gap_to_best=best_net - candidate.net_profit_krw)
        )

    if limit is not None:
        candidates = candidates[:limit]

    if candidates and candidates[0].unsold_kg > 0:
        notes.append(
            f"1위 도매처도 {candidates[0].unsold_kg:,}kg 은 매입하지 못합니다. "
            "잔여 물량은 다른 도매처로 분산 출하하세요."
        )

    return Recommendation(
        farm_id=farm.id,
        farm_name=farm.name,
        crop_id=crop.id,
        crop_name=crop.name,
        qty_kg=qty_kg,
        ship_date=ship_date,
        price_source=price_source,
        notes=notes,
        candidates=candidates,
    )


def _reliability_multiplier(score: float) -> float:
    """신뢰도 1.0 이면 1.0, 0.0 이면 1 − RELIABILITY_WEIGHT."""
    return 1.0 - RELIABILITY_WEIGHT * (1.0 - min(max(score, 0.0), 1.0))


def _with_reason(candidate: Candidate, *, gap_to_best: float) -> Candidate:
    return replace(candidate, reason=_build_reason(candidate, gap_to_best))


def _build_reason(c: Candidate, gap_to_best: float) -> str:
    fee_pct = c.fee_rate * 100
    fee_label = f"{fee_pct:.0f}%" if float(fee_pct).is_integer() else f"{fee_pct:.1f}%"
    sentence = (
        f"{c.rank}위 · 예상 순수익 {_format_krw(round(c.net_profit_krw))} — "
        f"단가 {c.unit_price_krw:,}원/kg 으로 {c.sellable_kg:,}kg 매입, "
        f"운송비 {_format_krw(round(c.transport_cost_krw))}({c.distance_km:.1f}km), "
        f"수수료 {fee_label} {_format_krw(round(c.fee_krw))}."
    )
    if c.unsold_kg > 0:
        sentence += (
            f" 구매 가능량이 {c.capacity_kg:,}kg 이라 "
            f"{c.unsold_kg:,}kg 이 남습니다."
        )
    if c.reliability.score < RELIABILITY_WARN_BELOW:
        rate = c.reliability.raw_rate or 0.0
        sentence += (
            f" 최근 거래 이행률 {rate * 100:.0f}%"
            f"({c.reliability.decided}건 중 {c.reliability.fulfilled}건)로 "
            "순위를 낮춰 반영했습니다."
        )
    if c.rank > 1 and gap_to_best > 0:
        sentence += f" 1위 대비 {_format_krw(round(gap_to_best))} 낮습니다."
    return sentence


def _format_krw(amount: int) -> str:
    """123456 → '12만 3,456원' — SPEC 5.2 표의 표기 방식."""
    sign = "-" if amount < 0 else ""
    man, rest = divmod(abs(amount), 10_000)
    if man and rest:
        return f"{sign}{man:,}만 {rest:,}원"
    if man:
        return f"{sign}{man:,}만원"
    return f"{sign}{rest:,}원"


# --------------------------------------------------------------------------
# 거래 기록 — 피드백 루프의 쓰기 쪽 (SPEC 7.1)
# --------------------------------------------------------------------------


def record_deal(
    session: Session,
    *,
    shipment_id: int,
    wholesaler_id: int,
    status: DealStatus = DealStatus.ACCEPTED,
    agreed_price_krw: int | None = None,
    decided_on: date | None = None,
) -> Deal:
    """농가가 실제로 고른 거래처를 ``deals`` 에 남긴다.

    - 같은 출하·도매처에 이미 ``proposed`` 행이 있으면 새로 만들지 않고 갱신한다
      (추천 제시 → 농가 선택이 한 행의 상태 변화가 되도록).
    - 이행 상태로 기록하면 같은 출하의 나머지 ``proposed`` 행은 ``rejected`` 로
      닫는다. 이것이 다음 추천에 들어가는 음의 신호다.
    - ``decided_on`` 을 주지 않으면 출하일을 쓴다. 벽시계 시간을 쓰지 않는다
      (docs/ARCHITECTURE.md 6절 결정론).
    """
    shipment = session.get(Shipment, shipment_id)
    if shipment is None:
        raise RecommendationError(f"shipment {shipment_id} not found")
    wholesaler = session.get(Wholesaler, wholesaler_id)
    if wholesaler is None:
        raise RecommendationError(f"wholesaler {wholesaler_id} not found")

    if agreed_price_krw is None:
        sellable = min(shipment.qty_kg, wholesaler.capacity_kg)
        agreed_price_krw = wholesaler.unit_price_krw * sellable

    settled_on = None if status == DealStatus.PROPOSED else (decided_on or shipment.ship_date)

    deal = session.scalar(
        select(Deal).where(
            Deal.shipment_id == shipment_id,
            Deal.wholesaler_id == wholesaler_id,
            Deal.status == DealStatus.PROPOSED,
        )
    )
    if deal is None:
        deal = Deal(shipment_id=shipment_id, wholesaler_id=wholesaler_id)
        session.add(deal)
    deal.agreed_price_krw = agreed_price_krw
    deal.status = status
    deal.decided_on = settled_on

    if status in FULFILLED_STATUSES:
        others = session.scalars(
            select(Deal).where(
                Deal.shipment_id == shipment_id,
                Deal.wholesaler_id != wholesaler_id,
                Deal.status == DealStatus.PROPOSED,
            )
        )
        for other in others:
            other.status = DealStatus.REJECTED
            other.decided_on = settled_on

    session.commit()
    session.refresh(deal)
    return deal


def list_deals(
    session: Session,
    *,
    shipment_id: int | None = None,
    wholesaler_id: int | None = None,
) -> list[Deal]:
    stmt = select(Deal).order_by(Deal.id)
    if shipment_id is not None:
        stmt = stmt.where(Deal.shipment_id == shipment_id)
    if wholesaler_id is not None:
        stmt = stmt.where(Deal.wholesaler_id == wholesaler_id)
    return list(session.scalars(stmt))
