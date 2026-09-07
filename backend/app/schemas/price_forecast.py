"""AI 농산물 시세 예측 입출력 스키마 (SPEC 5.1)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.ml.price_model import MAX_HORIZON_DAYS
from app.services.price_forecast import DEFAULT_HORIZON_DAYS

#: 한 번에 비교할 수 있는 후보 출하일 수 — SPEC 5.1 표는 3개지만 여유를 둔다.
MAX_CANDIDATE_DATES = 10

_ORM = ConfigDict(from_attributes=True)


class ModelInfoOut(BaseModel):
    """예측 모델의 검증 지표 (SPEC 2.3)."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    #: 홀드아웃 백테스트 평균 절대 백분율 오차(%).
    mape_pct: float
    #: 홀드아웃으로 떼어 낸 기간(일).
    backtest_days: int
    #: 학습에 쓴 마지막 시세일.
    trained_through: date
    max_horizon_days: int


class ActualPointOut(BaseModel):
    model_config = _ORM

    date: date
    price_per_kg: int
    volume_kg: int


class ForecastPointOut(BaseModel):
    model_config = _ORM

    date: date
    horizon_days: int
    expected_price_per_kg: int
    #: 약 95% 신뢰구간의 하단·상단.
    lower_price_per_kg: int
    upper_price_per_kg: int
    expected_volume_kg: int
    #: 공급량 감소 예상 | 공급량 보통 | 공급량 증가 예상
    supply_outlook: str


class PriceForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    crop_id: int
    crop_name: str
    region_id: int
    region_name: str
    as_of: date
    horizon_days: int
    model: ModelInfoOut
    actuals: list[ActualPointOut]
    forecast: list[ForecastPointOut]


class ShippingWindowIn(BaseModel):
    """POST /api/forecast/shipping-window 요청 본문."""

    crop_id: int = Field(gt=0)
    region_id: int = Field(gt=0)
    #: 출하 예정 물량. SPEC 5.1 예제는 토마토 1,000kg.
    qty_kg: int = Field(gt=0, description="출하 예정 물량 (kg)")
    #: 비교할 출하 후보일. **첫 번째가 기준(baseline)** 이다.
    candidate_dates: list[date] = Field(min_length=1, max_length=MAX_CANDIDATE_DATES)
    #: 예측 기준일. 생략하면 시세 이력의 마지막 날.
    as_of: date | None = None


class ShippingWindowRowOut(BaseModel):
    model_config = _ORM

    date: date
    horizon_days: int
    expected_price_per_kg: int
    expected_revenue_krw: int
    #: 기준일 대비 예상 가격 변동률(%). 기준 행은 0.0.
    change_pct_vs_baseline: float
    lower_price_per_kg: int
    upper_price_per_kg: int
    expected_volume_kg: int
    supply_outlook: str
    #: 즉시 출하 가능 | 출하 유지 권장 | 조기 출하 검토
    guidance: str
    is_baseline: bool


class ShippingWindowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    crop_id: int
    crop_name: str
    region_id: int
    region_name: str
    qty_kg: int
    as_of: date
    baseline_date: date
    model: ModelInfoOut
    rows: list[ShippingWindowRowOut]


#: 라우터의 쿼리 파라미터 기본값·상한을 스키마 쪽에 모아 둔다.
HORIZON_DEFAULT = DEFAULT_HORIZON_DAYS
HORIZON_MAX = MAX_HORIZON_DAYS
