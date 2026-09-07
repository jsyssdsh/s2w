"""SPEC 5.3 — 도매처 맞춤 판매처 연계.

도매처 재고를 등급·잔여 판매기한·수량으로 읽고, 각 로트를 어떤 판매처
(대형마트 · 학교급식 · 가공업체 · 음식점 · 로컬푸드)로 보내야 하는지 계산한다.

계산 규칙
---------
1. **등급 사전확률(prior)** — SPEC 5.3 표가 정의하는 등급→판매처 우선순위.
   특상품→대형마트, 상품→학교급식, 규격 외→가공업체, 임박→음식점/로컬푸드.
2. **판매기한이 등급을 이긴다** — 잔여일이 ``NEAR_EXPIRY_DAYS`` 이하이면 로트의
   명목 등급과 무관하게 ``near_expiry`` 사전확률을 쓴다. 배분 순서도 잔여일이
   짧은 로트가 먼저다. 즉 긴급도가 등급 사전확률을 지배한다.
3. **최종 순위는 점수** — 등급 적합도 · 수요 적합도 · 거리로 매긴다. 긴급할수록
   거리 가중치가 오르고 등급 가중치가 내린다 (빨리 실어낼 수 있는 곳 우선).
4. **이중 배정 금지** — 한 응답 안에서 판매처의 수요량은 로트를 가로질러
   차감된다. 배정 합계는 절대 수요량을 넘지 않는다.

거리는 ARCHITECTURE 2절대로 ``app.services.geo.haversine_km`` 만 쓴다.
벽시계 시간은 쓰지 않는다 — 모든 진입점이 ``as_of: date`` 를 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Buyer, BuyerType, Crop, Demand, Grade, Inventory, Wholesaler
from app.seed import ANCHOR_DATE
from app.services.geo import haversine_km

#: 기능 코드의 ``as_of`` 기본값은 시드 기준일에 맞춘다 (ARCHITECTURE 6절).
DEFAULT_AS_OF: date = ANCHOR_DATE

#: 잔여 판매기한이 이 일수 이하이면 등급과 무관하게 "임박" 으로 취급한다.
NEAR_EXPIRY_DAYS = 3

#: 긴급도를 0–1 로 정규화하는 기간. 이보다 멀면 긴급도 0.
URGENCY_HORIZON_DAYS = 14

#: 이 거리에서 거리 적합도가 0 이 된다.
MAX_DISTANCE_KM = 120.0

#: 등급별 판매처 우선순위 (SPEC 5.3 표). 앞에 올수록 적합도가 높다.
GRADE_BUYER_PRIORS: dict[Grade, tuple[BuyerType, ...]] = {
    Grade.SPECIAL: (BuyerType.MART, BuyerType.LOCALFOOD),
    Grade.STANDARD: (BuyerType.SCHOOL_MEAL, BuyerType.MART, BuyerType.LOCALFOOD),
    Grade.OFFGRADE: (BuyerType.PROCESSOR, BuyerType.LOCALFOOD),
    Grade.NEAR_EXPIRY: (BuyerType.RESTAURANT, BuyerType.LOCALFOOD, BuyerType.PROCESSOR),
}

#: 우선순위 i 번째 판매처의 등급 적합도. 목록 밖이면 ``_PRIOR_FLOOR``.
_PRIOR_FIT = (1.0, 0.65, 0.40)
_PRIOR_FLOOR = 0.15

GRADE_LABEL: dict[Grade, str] = {
    Grade.SPECIAL: "특상품",
    Grade.STANDARD: "상품",
    Grade.OFFGRADE: "규격 외",
    Grade.NEAR_EXPIRY: "판매기한 임박",
}

GRADE_REASON: dict[Grade, str] = {
    Grade.SPECIAL: "외관과 크기가 균일해",
    Grade.STANDARD: "대용량 납품이 가능해",
    Grade.OFFGRADE: "품질은 정상이나 모양이 불규칙해",
    Grade.NEAR_EXPIRY: "판매기한이 임박해 신속한 판매가 필요하므로",
}

BUYER_TYPE_LABEL: dict[BuyerType, str] = {
    BuyerType.MART: "대형마트",
    BuyerType.SCHOOL_MEAL: "학교급식업체",
    BuyerType.PROCESSOR: "가공업체",
    BuyerType.RESTAURANT: "지역 음식점",
    BuyerType.LOCALFOOD: "로컬푸드 매장",
}


# --------------------------------------------------------------------------
# Result types — 서비스는 계산값을 그대로 돌려주고, 반올림은 표현 계층이 한다.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryLot:
    """도매처 재고 한 줄 + ``as_of`` 기준 잔여 판매기한."""

    id: int
    wholesaler_id: int
    crop_id: int
    crop_name: str
    grade: Grade
    qty_kg: int
    expiry_date: date | None
    days_remaining: int | None

    @property
    def is_near_expiry(self) -> bool:
        return self.days_remaining is not None and self.days_remaining <= NEAR_EXPIRY_DAYS

    @property
    def effective_grade(self) -> Grade:
        """판매기한이 등급을 이긴다 — 임박하면 명목 등급을 덮어쓴다."""
        return Grade.NEAR_EXPIRY if self.is_near_expiry else self.grade

    @property
    def urgency(self) -> float:
        """0(여유) – 1(오늘까지). 판매기한이 없으면 0."""
        if self.days_remaining is None:
            return 0.0
        remaining = max(0, min(self.days_remaining, URGENCY_HORIZON_DAYS))
        return (URGENCY_HORIZON_DAYS - remaining) / URGENCY_HORIZON_DAYS


@dataclass(frozen=True)
class BuyerMatch:
    """로트 하나에 대한 판매처 한 곳의 추천."""

    buyer_id: int
    buyer_name: str
    buyer_type: BuyerType
    distance_km: float
    demand_kg: int
    matched_qty_kg: int
    score: float
    grade_fit: float
    demand_fit: float
    distance_fit: float
    reason: str


@dataclass
class LotRecommendation:
    lot: InventoryLot
    matches: list[BuyerMatch] = field(default_factory=list)

    @property
    def allocated_kg(self) -> int:
        return sum(m.matched_qty_kg for m in self.matches)

    @property
    def unallocated_kg(self) -> int:
        return self.lot.qty_kg - self.allocated_kg


@dataclass(frozen=True)
class BuyerMatchResult:
    wholesaler_id: int
    wholesaler_name: str
    crop_id: int
    crop_name: str
    as_of: date
    lots: list[LotRecommendation]

    @property
    def total_qty_kg(self) -> int:
        return sum(lot.lot.qty_kg for lot in self.lots)

    @property
    def total_allocated_kg(self) -> int:
        return sum(lot.allocated_kg for lot in self.lots)


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------


def get_wholesaler(session: Session, wholesaler_id: int) -> Wholesaler | None:
    return session.get(Wholesaler, wholesaler_id)


def get_crop(session: Session, crop_id: int) -> Crop | None:
    return session.get(Crop, crop_id)


def _days_remaining(expiry: date | None, as_of: date) -> int | None:
    return None if expiry is None else (expiry - as_of).days


def list_inventory(
    session: Session,
    wholesaler_id: int,
    *,
    crop_id: int | None = None,
    as_of: date = DEFAULT_AS_OF,
) -> list[InventoryLot]:
    """도매처 재고 로트 목록 — 잔여 판매기한이 짧은 순."""
    stmt = (
        select(Inventory, Crop)
        .join(Crop, Crop.id == Inventory.crop_id)
        .where(Inventory.wholesaler_id == wholesaler_id)
    )
    if crop_id is not None:
        stmt = stmt.where(Inventory.crop_id == crop_id)

    lots = [
        InventoryLot(
            id=row.Inventory.id,
            wholesaler_id=row.Inventory.wholesaler_id,
            crop_id=row.Inventory.crop_id,
            crop_name=row.Crop.name,
            grade=row.Inventory.grade,
            qty_kg=row.Inventory.qty_kg,
            expiry_date=row.Inventory.expiry_date,
            days_remaining=_days_remaining(row.Inventory.expiry_date, as_of),
        )
        for row in session.execute(stmt)
    ]
    return sorted(lots, key=_urgency_sort_key)


def _urgency_sort_key(lot: InventoryLot) -> tuple[int, int, int]:
    """판매기한이 짧은 로트가 먼저 판매처를 잡는다 (기한 없는 로트는 마지막)."""
    if lot.days_remaining is None:
        return (1, 0, lot.id)
    return (0, lot.days_remaining, lot.id)


def _buyer_capacity(
    session: Session, crop_id: int, as_of: date
) -> list[tuple[Buyer, int]]:
    """(판매처, 이 품목에 대한 수요량) — 품목별 수요가 있으면 그것을 쓰고,
    없으면 판매처의 일반 수요량(``buyers.demand_kg``)을 사전확률로 쓴다."""
    buyers = list(session.scalars(select(Buyer).order_by(Buyer.id)))

    demand_stmt = select(Demand).where(
        Demand.crop_id == crop_id,
        Demand.period_start <= as_of,
        Demand.period_end >= as_of,
    )
    per_buyer: dict[int, int] = {}
    for demand in session.scalars(demand_stmt):
        per_buyer[demand.buyer_id] = per_buyer.get(demand.buyer_id, 0) + demand.qty_kg

    return [(b, per_buyer.get(b.id, b.demand_kg)) for b in buyers]


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _grade_fit(grade: Grade, buyer_type: BuyerType) -> float:
    priors = GRADE_BUYER_PRIORS.get(grade, ())
    if buyer_type not in priors:
        return _PRIOR_FLOOR
    rank = priors.index(buyer_type)
    return _PRIOR_FIT[rank] if rank < len(_PRIOR_FIT) else _PRIOR_FLOOR


def _distance_fit(distance_km: float) -> float:
    return max(0.0, 1.0 - distance_km / MAX_DISTANCE_KM)


def _weights(urgency: float) -> tuple[float, float, float]:
    """(등급, 수요, 거리) 가중치 — 합은 1.0.

    긴급할수록 등급 가중치가 거리 가중치로 옮겨간다. 판매기한이 임박하면
    "등급에 맞는 곳" 보다 "지금 바로 받아 갈 수 있는 가까운 곳" 이 중요하다.
    """
    grade_w = 0.45 - 0.25 * urgency
    distance_w = 0.20 + 0.25 * urgency
    return grade_w, 0.35, distance_w


def _reason(
    lot: InventoryLot,
    buyer: Buyer,
    matched_qty_kg: int,
    demand_kg: int,
    distance_km: float,
) -> str:
    grade = lot.effective_grade
    parts = [
        f"{GRADE_LABEL[lot.grade]} {lot.qty_kg}kg 중 {matched_qty_kg}kg — "
        f"{GRADE_REASON[grade]} {BUYER_TYPE_LABEL[buyer.type]}"
        f"({buyer.name}) 연계를 추천합니다."
    ]
    parts.append(f"수요 {demand_kg}kg 대비 {matched_qty_kg}kg 배정")
    parts.append(f"거리 {distance_km:.1f}km")
    if lot.days_remaining is not None:
        if lot.is_near_expiry:
            parts.append(f"판매기한 {lot.days_remaining}일 남아 최우선 배정")
        else:
            parts.append(f"판매기한 {lot.days_remaining}일 남음")
    return f"{parts[0]} ({', '.join(parts[1:])})"


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def match_buyers(
    session: Session,
    wholesaler: Wholesaler,
    crop: Crop,
    *,
    as_of: date = DEFAULT_AS_OF,
) -> BuyerMatchResult:
    """재고 로트를 판매처에 배분한다 (SPEC 5.3).

    로트는 판매기한이 짧은 순으로 처리되고, 각 로트는 점수가 높은 판매처부터
    남은 수요만큼 채운다. ``remaining`` 은 응답 전체에서 공유되므로 한 판매처의
    수요량이 여러 로트에 중복 배정되지 않는다.
    """
    lots = list_inventory(session, wholesaler.id, crop_id=crop.id, as_of=as_of)
    capacity = _buyer_capacity(session, crop.id, as_of)
    remaining: dict[int, int] = {buyer.id: max(0, demand) for buyer, demand in capacity}
    total_demand: dict[int, int] = dict(remaining)

    distance: dict[int, float] = {
        buyer.id: haversine_km(wholesaler.lat, wholesaler.lon, buyer.lat, buyer.lon)
        for buyer, _ in capacity
    }

    recommendations: list[LotRecommendation] = []
    for lot in lots:
        recommendation = LotRecommendation(lot=lot)
        recommendations.append(recommendation)
        lot_remaining = lot.qty_kg
        grade = lot.effective_grade
        grade_w, demand_w, distance_w = _weights(lot.urgency)

        while lot_remaining > 0:
            best: tuple[float, Buyer, float, float, float] | None = None
            for buyer, _ in capacity:
                available = remaining[buyer.id]
                if available <= 0:
                    continue
                grade_fit = _grade_fit(grade, buyer.type)
                demand_fit = min(available, lot_remaining) / lot_remaining
                distance_fit = _distance_fit(distance[buyer.id])
                score = (
                    grade_w * grade_fit
                    + demand_w * demand_fit
                    + distance_w * distance_fit
                )
                candidate = (score, buyer, grade_fit, demand_fit, distance_fit)
                # 동점이면 가까운 곳, 그래도 같으면 id 가 작은 곳.
                if best is None or (score, -distance[buyer.id], -buyer.id) > (
                    best[0],
                    -distance[best[1].id],
                    -best[1].id,
                ):
                    best = candidate
            if best is None:
                break  # 남은 수요가 있는 판매처가 없다 — 미배정으로 남긴다.

            score, buyer, grade_fit, demand_fit, distance_fit = best
            matched = min(remaining[buyer.id], lot_remaining)
            remaining[buyer.id] -= matched
            lot_remaining -= matched
            recommendation.matches.append(
                BuyerMatch(
                    buyer_id=buyer.id,
                    buyer_name=buyer.name,
                    buyer_type=buyer.type,
                    distance_km=distance[buyer.id],
                    demand_kg=total_demand[buyer.id],
                    matched_qty_kg=matched,
                    score=score,
                    grade_fit=grade_fit,
                    demand_fit=demand_fit,
                    distance_fit=distance_fit,
                    reason=_reason(
                        lot, buyer, matched, total_demand[buyer.id], distance[buyer.id]
                    ),
                )
            )

    # 응답은 재고 조회와 같은 순서(판매기한 짧은 순)를 유지한다.
    return BuyerMatchResult(
        wholesaler_id=wholesaler.id,
        wholesaler_name=wholesaler.name,
        crop_id=crop.id,
        crop_name=crop.name,
        as_of=as_of,
        lots=recommendations,
    )
