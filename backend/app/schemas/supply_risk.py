"""지역별 수급 위험 조기 알림 API 스키마 (SPEC 5.4)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.schemas.reference import CropOut, RegionOut
from app.services import supply_risk as service


class WindowOut(BaseModel):
    """분석 기간."""

    start: date
    end: date

    @classmethod
    def of(cls, window: service.AnalysisWindow) -> "WindowOut":
        return cls(start=window.start, end=window.end)


class VolumeBreakdownOut(BaseModel):
    """SPEC 5.4 "소급 분석 결과" 표 (kg)."""

    model_config = ConfigDict(from_attributes=True)

    farm_shipment_kg: int          # 농가 출하 예정량
    wholesaler_inventory_kg: int   # 도매처 기존 재고량
    total_supply_kg: int           # 전체 공급량
    buyer_demand_kg: int           # 판매처 구매 수요량
    excess_supply_kg: int          # 예상 초과 공급량 (음수면 공급 부족)


class MitigationActionOut(BaseModel):
    """SPEC 5.4 "초과 물량 대응 방안" 한 줄."""

    model_config = ConfigDict(from_attributes=True)

    channel: service.MitigationChannel
    label: str
    qty_kg: int          # 처리 물량
    capacity_kg: int     # 이 채널이 감당 가능한 상한
    headroom_kg: int     # 아직 남은 여력
    detail: str


class MitigationPlanOut(BaseModel):
    """배분 결과. ``planned_kg + shortfall_kg == target_kg``."""

    model_config = ConfigDict(from_attributes=True)

    actions: list[MitigationActionOut]
    target_kg: int       # 처리해야 하는 물량 = max(0, 예상 초과 공급량)
    planned_kg: int
    shortfall_kg: int
    is_fully_covered: bool


class SupplyRiskOut(BaseModel):
    """``GET /api/supply-risk`` 응답."""

    region: RegionOut
    crop: CropOut
    window: WindowOut
    volumes: VolumeBreakdownOut
    excess_ratio: float
    risk_tier: service.RiskTier
    mitigation: MitigationPlanOut

    @classmethod
    def of(cls, assessment: service.SupplyRiskAssessment) -> "SupplyRiskOut":
        return cls(
            region=RegionOut.model_validate(assessment.region),
            crop=CropOut.model_validate(assessment.crop),
            window=WindowOut.of(assessment.window),
            volumes=VolumeBreakdownOut.model_validate(assessment.volumes),
            excess_ratio=assessment.excess_ratio,
            risk_tier=assessment.risk_tier,
            mitigation=MitigationPlanOut.model_validate(assessment.mitigation),
        )


class AlertOut(BaseModel):
    """``GET /api/alerts`` 한 건 — 유통업체 대시보드용 요약 (SPEC 4.3)."""

    region: RegionOut
    crop: CropOut
    window: WindowOut
    risk_tier: service.RiskTier
    excess_ratio: float
    total_supply_kg: int
    buyer_demand_kg: int
    excess_supply_kg: int
    shortfall_kg: int
    headline: str

    @classmethod
    def of(cls, assessment: service.SupplyRiskAssessment) -> "AlertOut":
        return cls(
            region=RegionOut.model_validate(assessment.region),
            crop=CropOut.model_validate(assessment.crop),
            window=WindowOut.of(assessment.window),
            risk_tier=assessment.risk_tier,
            excess_ratio=assessment.excess_ratio,
            total_supply_kg=assessment.volumes.total_supply_kg,
            buyer_demand_kg=assessment.volumes.buyer_demand_kg,
            excess_supply_kg=assessment.volumes.excess_supply_kg,
            shortfall_kg=assessment.mitigation.shortfall_kg,
            headline=assessment.headline,
        )
