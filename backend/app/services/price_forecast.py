"""시세 예측 도메인 로직 (SPEC 5.1).

두 가지를 만든다:

* **가격 추이** — 차트를 그릴 최근 실적 + 지평까지의 일별 예측.
* **출하일 비교표** — SPEC 5.1 의 "토마토 1,000kg 출하일 결정 비교" 를 그대로
  재현한다. 후보 날짜마다 예상 가격·매출·기준 대비 변동률·시장 상황·시스템
  안내를 한 줄씩 낸다.

계산만 하고 반올림은 하지 않는다 (docs/ARCHITECTURE.md 5절 — 표현 계층의 일).
정수 KRW 로 떨어져야 하는 값만 여기서 정수로 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.price_model import (
    MAX_HORIZON_DAYS,
    InsufficientHistoryError,
    Prediction,
    PriceModel,
    get_model,
)
from app.models import Crop, MarketPrice, Region

# --------------------------------------------------------------------------
# 판정 기준 — SPEC 5.1 의 "예상 시장 상황" 과 "시스템 안내" 를 만드는 임계값.
# 하나의 블록에 모아 두어 튜닝 지점이 흩어지지 않게 한다.
# --------------------------------------------------------------------------

#: 예상 거래량 / 계절 평년 거래량 비율. 이 아래면 공급이 조인다고 본다.
SUPPLY_TIGHT_RATIO = 0.97
#: 이 위면 공급이 풀린다고 본다.
SUPPLY_LOOSE_RATIO = 1.03

#: 기준일 대비 가격 변동률(%)이 이 위면 값이 오르는 중 → 출하를 미뤄도 좋다.
GUIDANCE_RISING_PCT = 0.0
#: 이 아래로 떨어지면 값이 빠지는 중 → 조기 출하를 검토한다.
GUIDANCE_FALLING_PCT = -3.0

#: 차트에 함께 그릴 과거 실적 구간(일).
DEFAULT_ACTUAL_DAYS = 60
#: GET /api/forecast/price 의 기본 지평(일) — SPEC 5.1 의 2주 시야.
DEFAULT_HORIZON_DAYS = 14

SUPPLY_DECREASE = "공급량 감소 예상"
SUPPLY_NORMAL = "공급량 보통"
SUPPLY_INCREASE = "공급량 증가 예상"

GUIDANCE_SHIP_NOW = "즉시 출하 가능"
GUIDANCE_HOLD = "출하 유지 권장"
GUIDANCE_SHIP_EARLY = "조기 출하 검토"


class UnknownTargetError(LookupError):
    """존재하지 않는 품목·지역."""


class ForecastRangeError(ValueError):
    """지평이나 후보 날짜가 모델이 다룰 수 있는 범위를 벗어남."""


# --------------------------------------------------------------------------
# 결과 자료구조
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ActualPoint:
    date: date
    price_per_kg: int
    volume_kg: int


@dataclass(frozen=True)
class ForecastPoint:
    date: date
    horizon_days: int
    expected_price_per_kg: int
    lower_price_per_kg: int
    upper_price_per_kg: int
    expected_volume_kg: int
    supply_outlook: str


@dataclass(frozen=True)
class ModelInfo:
    """SPEC 2.3 이 요구하는 "예측 정확도" 를 응답에 그대로 실어 보낸다."""

    mape_pct: float
    backtest_days: int
    trained_through: date
    max_horizon_days: int


@dataclass(frozen=True)
class PriceForecast:
    crop_id: int
    crop_name: str
    region_id: int
    region_name: str
    as_of: date
    horizon_days: int
    model: ModelInfo
    actuals: list[ActualPoint]
    forecast: list[ForecastPoint]


@dataclass(frozen=True)
class ShippingWindowRow:
    """SPEC 5.1 비교표의 한 열(= 후보 출하일 한 개)."""

    date: date
    horizon_days: int
    expected_price_per_kg: int
    expected_revenue_krw: int
    change_pct_vs_baseline: float
    lower_price_per_kg: int
    upper_price_per_kg: int
    expected_volume_kg: int
    supply_outlook: str
    guidance: str
    is_baseline: bool


@dataclass(frozen=True)
class ShippingWindow:
    crop_id: int
    crop_name: str
    region_id: int
    region_name: str
    qty_kg: int
    as_of: date
    baseline_date: date
    model: ModelInfo
    rows: list[ShippingWindowRow]


# --------------------------------------------------------------------------
# 판정 규칙
# --------------------------------------------------------------------------


def supply_outlook(expected_volume_kg: float, seasonal_volume_kg: float) -> str:
    """예상 출하량을 계절 평년과 견줘 시장 상황 라벨을 만든다.

    평년 대비 물량이 적으면 값이 받쳐지고(공급량 감소 예상), 많으면 눌린다
    (공급량 증가 예상) — SPEC 5.1 표의 "예상 시장 상황" 열.
    """
    if seasonal_volume_kg <= 0:
        return SUPPLY_NORMAL
    ratio = expected_volume_kg / seasonal_volume_kg
    if ratio < SUPPLY_TIGHT_RATIO:
        return SUPPLY_DECREASE
    if ratio > SUPPLY_LOOSE_RATIO:
        return SUPPLY_INCREASE
    return SUPPLY_NORMAL


def guidance_for(change_pct_vs_baseline: float) -> str:
    """기준일 대비 가격 변동률에서 시스템 안내 문구를 고른다."""
    if change_pct_vs_baseline > GUIDANCE_RISING_PCT:
        return GUIDANCE_HOLD
    if change_pct_vs_baseline < GUIDANCE_FALLING_PCT:
        return GUIDANCE_SHIP_EARLY
    return GUIDANCE_SHIP_NOW


# --------------------------------------------------------------------------
# 조회 헬퍼
# --------------------------------------------------------------------------


def _crop_and_region(session: Session, crop_id: int, region_id: int) -> tuple[Crop, Region]:
    crop = session.get(Crop, crop_id)
    if crop is None:
        raise UnknownTargetError(f"crop_id={crop_id} 품목을 찾을 수 없다")
    region = session.get(Region, region_id)
    if region is None:
        raise UnknownTargetError(f"region_id={region_id} 지역을 찾을 수 없다")
    return crop, region


def _model_info(model: PriceModel) -> ModelInfo:
    return ModelInfo(
        mape_pct=model.mape_pct,
        backtest_days=model.backtest_days,
        trained_through=model.trained_through,
        max_horizon_days=MAX_HORIZON_DAYS,
    )


def _to_forecast_point(prediction: Prediction) -> ForecastPoint:
    return ForecastPoint(
        date=prediction.date,
        horizon_days=prediction.horizon_days,
        expected_price_per_kg=round(prediction.expected_price_per_kg),
        lower_price_per_kg=round(prediction.lower_price_per_kg),
        upper_price_per_kg=round(prediction.upper_price_per_kg),
        expected_volume_kg=round(prediction.expected_volume_kg),
        supply_outlook=supply_outlook(
            prediction.expected_volume_kg, prediction.seasonal_volume_kg
        ),
    )


def _resolve_model(
    session: Session, crop_id: int, region_id: int
) -> tuple[Crop, Region, PriceModel]:
    crop, region = _crop_and_region(session, crop_id, region_id)
    try:
        model = get_model(session, crop_id, region_id)
    except InsufficientHistoryError as exc:
        available = available_region_ids(session, crop_id)
        raise UnknownTargetError(
            f"{exc} (시세 이력이 있는 region_id: {available or '없음'})"
        ) from exc
    return crop, region, model


def _resolve_as_of(model: PriceModel, as_of: date | None) -> date:
    """``as_of`` 기본값은 시세 이력의 마지막 날 (시드에서는 ANCHOR_DATE)."""
    if as_of is None:
        return model.trained_through
    if as_of > model.trained_through:
        raise ForecastRangeError(
            f"as_of {as_of} 는 마지막 시세일 {model.trained_through} 이후다"
        )
    if as_of < model.observations[0].date:
        raise ForecastRangeError(
            f"as_of {as_of} 이전의 시세 이력이 없다"
        )
    return as_of


# --------------------------------------------------------------------------
# 1. 가격 추이 — GET /api/forecast/price
# --------------------------------------------------------------------------


def price_forecast(
    session: Session,
    crop_id: int,
    region_id: int,
    horizon: int = DEFAULT_HORIZON_DAYS,
    as_of: date | None = None,
    actual_days: int = DEFAULT_ACTUAL_DAYS,
) -> PriceForecast:
    """``as_of`` 기준 ``horizon`` 일치 일별 예측과 최근 실적을 함께 돌려준다."""
    if horizon < 1 or horizon > MAX_HORIZON_DAYS:
        raise ForecastRangeError(f"horizon 은 1~{MAX_HORIZON_DAYS}일이어야 한다")

    crop, region, model = _resolve_model(session, crop_id, region_id)
    origin = _resolve_as_of(model, as_of)

    window_start = origin - timedelta(days=actual_days - 1)
    actuals = [
        ActualPoint(
            date=o.date, price_per_kg=o.price_per_kg, volume_kg=o.volume_kg
        )
        for o in model.observations
        if window_start <= o.date <= origin
    ]

    return PriceForecast(
        crop_id=crop.id,
        crop_name=crop.name,
        region_id=region.id,
        region_name=region.name,
        as_of=origin,
        horizon_days=horizon,
        model=_model_info(model),
        actuals=actuals,
        forecast=[
            _to_forecast_point(p) for p in model.predict_series(horizon, as_of=origin)
        ],
    )


# --------------------------------------------------------------------------
# 2. 출하일 비교표 — POST /api/forecast/shipping-window
# --------------------------------------------------------------------------


def shipping_window(
    session: Session,
    crop_id: int,
    region_id: int,
    qty_kg: int,
    candidate_dates: list[date],
    as_of: date | None = None,
) -> ShippingWindow:
    """후보 출하일들을 SPEC 5.1 비교표 형태로 나란히 세운다.

    첫 후보일이 **기준(baseline)** 이다. 변동률·시스템 안내는 모두 그 행의
    예상 가격을 기준으로 계산한다.
    """
    if qty_kg <= 0:
        raise ForecastRangeError("qty_kg 는 1 이상이어야 한다")
    if not candidate_dates:
        raise ForecastRangeError("candidate_dates 가 비어 있다")

    crop, region, model = _resolve_model(session, crop_id, region_id)
    origin = _resolve_as_of(model, as_of)

    # 입력 순서는 유지하되, 중복 날짜는 첫 번째만 남긴다.
    ordered: list[date] = []
    for day in candidate_dates:
        if day not in ordered:
            ordered.append(day)

    for day in ordered:
        horizon = (day - origin).days
        if horizon < 0:
            raise ForecastRangeError(f"후보일 {day} 가 기준일 {origin} 보다 앞선다")
        if horizon > MAX_HORIZON_DAYS:
            raise ForecastRangeError(
                f"후보일 {day} 는 기준일에서 {horizon}일 뒤 — 최대 {MAX_HORIZON_DAYS}일"
            )

    predictions = [model.predict(day, as_of=origin) for day in ordered]
    baseline_price = predictions[0].expected_price_per_kg

    rows: list[ShippingWindowRow] = []
    for index, prediction in enumerate(predictions):
        change_pct = (
            (prediction.expected_price_per_kg - baseline_price) / baseline_price * 100.0
            if baseline_price
            else 0.0
        )
        rows.append(
            ShippingWindowRow(
                date=prediction.date,
                horizon_days=prediction.horizon_days,
                expected_price_per_kg=round(prediction.expected_price_per_kg),
                # 판매금액 = 예상 단가 × 출하량 (수수료·운송비는 SPEC 5.2 의 몫).
                expected_revenue_krw=round(
                    prediction.expected_price_per_kg * qty_kg
                ),
                change_pct_vs_baseline=change_pct,
                lower_price_per_kg=round(prediction.lower_price_per_kg),
                upper_price_per_kg=round(prediction.upper_price_per_kg),
                expected_volume_kg=round(prediction.expected_volume_kg),
                supply_outlook=supply_outlook(
                    prediction.expected_volume_kg, prediction.seasonal_volume_kg
                ),
                guidance=guidance_for(change_pct),
                is_baseline=index == 0,
            )
        )

    return ShippingWindow(
        crop_id=crop.id,
        crop_name=crop.name,
        region_id=region.id,
        region_name=region.name,
        qty_kg=qty_kg,
        as_of=origin,
        baseline_date=ordered[0],
        model=_model_info(model),
        rows=rows,
    )


def available_region_ids(session: Session, crop_id: int) -> list[int]:
    """해당 품목의 시세 이력이 있는 지역 — 404 응답 메시지에 붙여 준다."""
    return list(
        session.scalars(
            select(MarketPrice.region_id)
            .where(MarketPrice.crop_id == crop_id)
            .distinct()
            .order_by(MarketPrice.region_id)
        )
    )
