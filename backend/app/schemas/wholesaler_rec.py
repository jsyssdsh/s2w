"""도매처 추천 · 거래 기록의 입출력 스키마 (SPEC 5.2 / 7.1).

여기가 표현 계층이다 (docs/ARCHITECTURE.md 5절): 서비스가 돌려준 float 계산값을
정수 KRW 로 반올림하는 일은 전부 이 파일의 ``from_domain`` 안에서 일어난다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models import DealStatus
from app.services import wholesaler_rec as service


class WholesalerRecommendationIn(BaseModel):
    farm_id: int
    crop_id: int
    qty_kg: int = Field(gt=0, description="출하량 (kg)")
    ship_date: date
    use_forecast: bool = Field(
        default=False,
        description="단가를 SPEC 5.1 시세 예측값으로 대체한다. 예측 서비스가 "
        "없으면 도매처 고시 단가로 되돌아가고 notes 에 알린다.",
    )
    limit: int | None = Field(default=None, gt=0, description="상위 N개만 반환")


class ReliabilityOut(BaseModel):
    """도매처 거래 이행 이력 — 순위 조정의 근거 (SPEC 7.1)."""

    score: float = Field(description="스무딩된 이행률 0.0–1.0, 이력이 없으면 1.0")
    fulfilled: int
    decided: int
    proposed_total: int

    @classmethod
    def from_domain(cls, r: service.Reliability) -> "ReliabilityOut":
        return cls(
            score=round(r.score, 4),
            fulfilled=r.fulfilled,
            decided=r.decided,
            proposed_total=r.proposed_total,
        )


class WholesalerCandidateOut(BaseModel):
    rank: int
    wholesaler_id: int
    name: str
    distance_km: float
    unit_price_krw: int = Field(description="계산에 쓴 매입단가 (원/kg)")
    list_unit_price_krw: int = Field(description="도매처 고시 단가 (원/kg)")
    capacity_kg: int
    sellable_kg: int = Field(description="min(출하량, 구매 가능량)")
    unsold_kg: int = Field(description="이 도매처가 받지 못하는 잔여 물량")
    gross_krw: int = Field(description="판매금액 = 단가 × 구매량")
    transport_cost_krw: int = Field(description="운송비 = 거리 × km당 단가")
    fee_rate: float
    fee_krw: int = Field(description="수수료 = 판매금액 × 수수료율")
    net_profit_krw: int = Field(description="예상 순수익 = 판매금액 − 운송비 − 수수료")
    ranking_score_krw: int = Field(description="이행률을 반영한 정렬 기준값")
    reliability: ReliabilityOut
    reason: str

    @classmethod
    def from_domain(cls, c: service.Candidate) -> "WholesalerCandidateOut":
        return cls(
            rank=c.rank,
            wholesaler_id=c.wholesaler_id,
            name=c.name,
            distance_km=round(c.distance_km, 2),
            unit_price_krw=c.unit_price_krw,
            list_unit_price_krw=c.list_unit_price_krw,
            capacity_kg=c.capacity_kg,
            sellable_kg=c.sellable_kg,
            unsold_kg=c.unsold_kg,
            gross_krw=round(c.gross_krw),
            transport_cost_krw=round(c.transport_cost_krw),
            fee_rate=c.fee_rate,
            fee_krw=round(c.fee_krw),
            net_profit_krw=round(c.net_profit_krw),
            ranking_score_krw=round(c.ranking_score_krw),
            reliability=ReliabilityOut.from_domain(c.reliability),
            reason=c.reason,
        )


class WholesalerRecommendationOut(BaseModel):
    farm_id: int
    farm_name: str
    crop_id: int
    crop_name: str
    qty_kg: int
    ship_date: date
    price_source: str = Field(description='"static" 또는 "forecast"')
    notes: list[str]
    candidates: list[WholesalerCandidateOut]

    @classmethod
    def from_domain(cls, r: service.Recommendation) -> "WholesalerRecommendationOut":
        return cls(
            farm_id=r.farm_id,
            farm_name=r.farm_name,
            crop_id=r.crop_id,
            crop_name=r.crop_name,
            qty_kg=r.qty_kg,
            ship_date=r.ship_date,
            price_source=r.price_source,
            notes=r.notes,
            candidates=[WholesalerCandidateOut.from_domain(c) for c in r.candidates],
        )


class DealIn(BaseModel):
    """농가의 실제 거래 선택 (SPEC 7.1 마지막 단계)."""

    shipment_id: int
    wholesaler_id: int
    status: DealStatus = Field(
        default=DealStatus.ACCEPTED,
        description="proposed 로 추천을 기록하고, accepted/rejected/settled 로 "
        "농가의 선택을 남긴다.",
    )
    agreed_price_krw: int | None = Field(
        default=None,
        gt=0,
        description="생략하면 단가 × min(출하량, 구매 가능량) 으로 채운다.",
    )
    decided_on: date | None = Field(
        default=None, description="생략하면 출하일. proposed 면 비워 둔다."
    )
    alternatives: list[int] = Field(
        default_factory=list,
        description="농가가 함께 본, 그러나 고르지 않은 도매처 id. 이행 상태로 "
        "기록할 때 이들이 rejected 로 닫혀 다음 추천의 음의 신호가 된다.",
    )


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    wholesaler_id: int
    agreed_price_krw: int
    status: DealStatus
    decided_on: date | None
