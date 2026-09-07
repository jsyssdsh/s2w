"""AI 농산물 시세 예측 모델 (SPEC 5.1).

과거 도매가격·거래량과 기상 데이터를 학습해 **미래 특정 날짜의** 가격과
거래량을 추정한다. SPEC 6.2 가 지정한 scikit-learn 을 쓴다.

설계 요점
---------
* **직접 다중 지평(direct multi-horizon)** — 재귀 예측처럼 오차를 누적시키지
  않도록, "기준일 t 의 관측치 + 지평 h" 를 입력으로 받아 ``t+h`` 의 값을 바로
  맞히는 회귀 모델 하나를 학습한다. 학습 표본은 (t, h) 쌍 전체다.
* **누설 없음** — 특징은 전부 기준일 t 시점에 알 수 있는 값뿐이다. 미래 기상은
  쓰지 않고, 예측 대상일에서 가져오는 것은 달력값(계절성)뿐이다.
* **결정론** — 고정 ``RANDOM_STATE``, 부분표집 없음. 같은 데이터면 같은 숫자가
  나온다 (docs/ARCHITECTURE.md 6절).
* **백테스트** — 마지막 ``BACKTEST_DAYS`` 일을 홀드아웃으로 떼어 MAPE 를 재고,
  같은 홀드아웃의 잔차로 지평별 신뢰구간 폭을 만든다. SPEC 2.3 의 "예측
  정확도 검증" 요구를 코드로 만족시키는 지점이다.

학습된 모델은 ``DB_PATH`` 옆에 joblib 로 캐시된다. 데이터 지문(행 수·마지막
날짜·마지막 가격)이 달라지면 캐시를 버리고 다시 학습한다.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MarketPrice, WeatherDaily

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Training constants — every knob of the model lives here.
# --------------------------------------------------------------------------

#: 예측 가능한 최대 지평(일). 학습 표본도 1..MAX_HORIZON_DAYS 로 만든다.
MAX_HORIZON_DAYS = 30

#: 가격 시차 특징 (일). 기준일 t 에서 t, t-6, t-13, t-29 의 가격을 본다.
PRICE_LAG_DAYS = (1, 7, 14, 30)

#: 이동평균 창 (일).
ROLLING_WINDOWS = (7, 30)

#: 백테스트 홀드아웃 길이 — 시드 데이터의 마지막 60일.
BACKTEST_DAYS = 60

#: 홀드아웃 MAPE 상한(%). 이 위로 올라가면 모델이 망가진 것으로 본다.
#: 시드 데이터 기준 실측치는 docs/API.md 에 기록한다.
MAPE_CEILING_PCT = 12.0

#: 신뢰구간 배수 — 잔차가 정규분포라고 보고 약 95% 구간.
CONFIDENCE_Z = 1.96

#: 잔차 표본이 너무 적은 지평에서 쓰는 최소 상대 오차(가격 대비 비율).
MIN_RELATIVE_BAND = 0.01

RANDOM_STATE = 20260808

#: 히스토그램 기반 부스팅. 조기중단을 끄고 시드를 고정해 완전 결정론으로 둔다
#: (스레드 수가 달라져도 같은 값이 나온다 — tests/test_price_forecast.py 가 확인).
_ESTIMATOR_PARAMS = dict(
    max_iter=300,
    learning_rate=0.05,
    max_depth=4,
    early_stopping=False,
    random_state=RANDOM_STATE,
)

#: 계절 평년 거래량을 구할 때 대상일 전후로 볼 날짜 폭 (일).
SEASONAL_WINDOW_DAYS = 7

_FEATURE_NAMES: tuple[str, ...] = (
    *(f"price_lag_{d}d" for d in PRICE_LAG_DAYS),
    *(f"price_roll_mean_{w}d" for w in ROLLING_WINDOWS),
    "volume",
    *(f"volume_roll_mean_{w}d" for w in ROLLING_WINDOWS),
    "temp_avg",
    "rain_mm",
    "sunshine_hours",
    "target_doy_sin",
    "target_doy_cos",
    "horizon_days",
)


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """(crop, region) 의 하루치 관측 — 시세와 그날의 기상."""

    date: date
    price_per_kg: int
    volume_kg: int
    temp_avg: float
    rain_mm: float
    sunshine_hours: float


@dataclass(frozen=True)
class Prediction:
    """모델이 내놓는 하루치 예측."""

    date: date
    horizon_days: int
    expected_price_per_kg: float
    lower_price_per_kg: float
    upper_price_per_kg: float
    expected_volume_kg: float
    seasonal_volume_kg: float
    #: 관측된 실제값을 그대로 돌려준 경우 (지평 0) True.
    is_actual: bool


def load_observations(
    session: Session, crop_id: int, region_id: int
) -> list[Observation]:
    """``market_prices`` 를 같은 지역의 ``weather_daily`` 와 날짜로 이어 붙인다.

    기상 결측일은 버리지 않고 직전 관측값으로 앞으로 채운다 (SPEC 6.2 의
    "누락·오류 데이터를 정리" 단계). 맨 앞이 비어 있으면 첫 유효값을 쓴다.
    """
    prices = list(
        session.scalars(
            select(MarketPrice)
            .where(
                MarketPrice.crop_id == crop_id,
                MarketPrice.region_id == region_id,
            )
            .order_by(MarketPrice.date)
        )
    )
    if not prices:
        return []

    weather = {
        row.date: row
        for row in session.scalars(
            select(WeatherDaily).where(WeatherDaily.region_id == region_id)
        )
    }

    # 기상 결측은 직전 관측값으로 앞으로 채우고, 시계열 맨 앞이 비어 있으면
    # 첫 유효값으로 되메운다 (SPEC 6.2 "누락·오류 데이터를 정리" 단계).
    # 0.0 은 겨울철 평균기온으로 실제로 나오는 값이라 결측 표시로 쓸 수 없다.
    first_weather = next(
        (weather[p.date] for p in prices if p.date in weather), None
    )
    carried: tuple[float, float, float] = (
        (first_weather.temp_avg, first_weather.rain_mm, first_weather.sunshine_hours)
        if first_weather is not None
        else (0.0, 0.0, 0.0)
    )

    observations: list[Observation] = []
    for price in prices:
        row = weather.get(price.date)
        if row is not None:
            carried = (row.temp_avg, row.rain_mm, row.sunshine_hours)
        temp, rain, sun = carried
        observations.append(
            Observation(
                date=price.date,
                price_per_kg=price.price_per_kg,
                volume_kg=price.volume_kg,
                temp_avg=temp,
                rain_mm=rain,
                sunshine_hours=sun,
            )
        )
    return observations


# --------------------------------------------------------------------------
# Feature engineering
# --------------------------------------------------------------------------


def _seasonal_terms(day: date) -> tuple[float, float]:
    """연중 위치를 sin/cos 한 쌍으로 — 12월 31일과 1월 1일이 이어지도록."""
    angle = 2 * math.pi * (day.timetuple().tm_yday - 1) / 365.0
    return math.sin(angle), math.cos(angle)


def _rolling_means(values: np.ndarray, window: int) -> np.ndarray:
    """``values[i]`` 까지(포함)의 ``window`` 일 이동평균. 앞쪽은 있는 만큼 평균."""
    cumulative = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
    index = np.arange(len(values))
    start = np.maximum(0, index - window + 1)
    return (cumulative[index + 1] - cumulative[start]) / (index - start + 1)


def _origin_features(observations: list[Observation]) -> tuple[np.ndarray, int]:
    """기준일마다 "그날까지 알 수 있는" 특징 행렬을 만든다.

    반환값은 (행렬, 첫 유효 행 인덱스). 가장 긴 시차만큼은 앞쪽 행이 불완전해
    학습에서 제외한다.
    """
    prices = np.array([o.price_per_kg for o in observations], dtype=float)
    volumes = np.array([o.volume_kg for o in observations], dtype=float)

    columns: list[np.ndarray] = []
    for lag in PRICE_LAG_DAYS:
        shifted = np.empty_like(prices)
        offset = lag - 1  # lag=1 은 기준일 당일 가격
        shifted[:offset] = prices[0]  # 이력 이전은 첫 관측가로 메운다
        shifted[offset:] = prices[: len(prices) - offset]
        columns.append(shifted)
    for window in ROLLING_WINDOWS:
        columns.append(_rolling_means(prices, window))
    columns.append(volumes)
    for window in ROLLING_WINDOWS:
        columns.append(_rolling_means(volumes, window))
    columns.append(np.array([o.temp_avg for o in observations], dtype=float))
    columns.append(np.array([o.rain_mm for o in observations], dtype=float))
    columns.append(np.array([o.sunshine_hours for o in observations], dtype=float))

    return np.column_stack(columns), max(PRICE_LAG_DAYS) - 1


def _row(origin_row: np.ndarray, target_day: date, horizon: int) -> np.ndarray:
    sin_term, cos_term = _seasonal_terms(target_day)
    return np.concatenate((origin_row, [sin_term, cos_term, float(horizon)]))


def _supervised_frame(
    observations: list[Observation],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[date], np.ndarray]:
    """(X, y_price, y_volume, target_dates, horizons) 학습 표본.

    기준일 t 와 지평 h 의 모든 조합을 편다. 표본 하나가 "t 에서 t+h 를 맞혀라".
    """
    origin, first = _origin_features(observations)
    rows: list[np.ndarray] = []
    price_targets: list[float] = []
    volume_targets: list[float] = []
    target_dates: list[date] = []
    horizons: list[int] = []

    total = len(observations)
    for i in range(first, total):
        for horizon in range(1, MAX_HORIZON_DAYS + 1):
            j = i + horizon
            if j >= total:
                break
            target = observations[j]
            rows.append(_row(origin[i], target.date, horizon))
            price_targets.append(float(target.price_per_kg))
            volume_targets.append(float(target.volume_kg))
            target_dates.append(target.date)
            horizons.append(horizon)

    return (
        np.array(rows, dtype=float),
        np.array(price_targets, dtype=float),
        np.array(volume_targets, dtype=float),
        target_dates,
        np.array(horizons, dtype=int),
    )


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """평균 절대 백분율 오차(%). 시세는 항상 양수라 0 나눗셈은 없다."""
    return float(np.mean(np.abs((actual - predicted) / actual)) * 100.0)


# --------------------------------------------------------------------------
# The trained model
# --------------------------------------------------------------------------


@dataclass
class PriceModel:
    """(crop, region) 하나에 대해 학습이 끝난 시세 예측 모델."""

    crop_id: int
    region_id: int
    price_estimator: HistGradientBoostingRegressor
    volume_estimator: HistGradientBoostingRegressor
    #: 지평 → 잔차 표준편차(원/kg). 신뢰구간 폭의 근거.
    residual_std_by_horizon: dict[int, float]
    #: 홀드아웃 MAPE(%). SPEC 2.3 검증 지표.
    mape_pct: float
    backtest_days: int
    #: 계절 평년 거래량: day-of-year → 과거 같은 시기 평균 거래량.
    seasonal_volume_by_doy: dict[int, float]
    observations: list[Observation]
    #: 기준일별 특징 행렬 — 예측 때마다 다시 만들지 않도록 학습 시점에 붙여 둔다.
    origin_matrix: np.ndarray
    fingerprint: str

    # -- 조회 --------------------------------------------------------------

    @property
    def trained_through(self) -> date:
        return self.observations[-1].date

    @property
    def feature_names(self) -> tuple[str, ...]:
        return _FEATURE_NAMES

    def observation_on(self, day: date) -> Observation | None:
        # 시드는 하루도 빠짐없이 채우지만, 실데이터에는 구멍이 있을 수 있다.
        for observation in reversed(self.observations):
            if observation.date == day:
                return observation
            if observation.date < day:
                break
        return None

    def seasonal_volume(self, day: date) -> float:
        doy = day.timetuple().tm_yday
        known = self.seasonal_volume_by_doy
        if doy in known:
            return known[doy]
        # 윤일 등 표본이 없는 날은 전체 평균으로 대체한다.
        return float(np.mean(list(known.values()))) if known else 0.0

    # -- 예측 --------------------------------------------------------------

    def predict(self, target_day: date, as_of: date | None = None) -> Prediction:
        """``as_of`` 시점에서 ``target_day`` 의 시세·거래량을 추정한다.

        ``target_day`` 가 관측 구간 안이면(지평 0) 학습 데이터의 실측값을 그대로
        돌려준다 — SPEC 5.1 비교표의 "기준" 행이 실제 시세와 어긋나지 않도록.
        """
        origin_day = as_of or self.trained_through
        horizon = (target_day - origin_day).days
        if horizon < 0:
            raise ValueError(f"target_day {target_day} 는 기준일 {origin_day} 보다 앞선다")
        if horizon > MAX_HORIZON_DAYS:
            raise ValueError(
                f"지평 {horizon}일은 최대 {MAX_HORIZON_DAYS}일을 넘는다"
            )

        if horizon == 0:
            actual = self.observation_on(target_day)
            if actual is not None:
                return Prediction(
                    date=target_day,
                    horizon_days=0,
                    expected_price_per_kg=float(actual.price_per_kg),
                    lower_price_per_kg=float(actual.price_per_kg),
                    upper_price_per_kg=float(actual.price_per_kg),
                    expected_volume_kg=float(actual.volume_kg),
                    seasonal_volume_kg=self.seasonal_volume(target_day),
                    is_actual=True,
                )
            # 관측이 없으면 다음 날 모델로 근사한다.
            horizon = 1

        index = self._origin_index(origin_day)
        features = _row(self.origin_matrix[index], target_day, horizon).reshape(1, -1)

        price = float(self.price_estimator.predict(features)[0])
        volume = float(self.volume_estimator.predict(features)[0])
        band = self._band(horizon, price)
        return Prediction(
            date=target_day,
            horizon_days=horizon,
            expected_price_per_kg=price,
            lower_price_per_kg=max(0.0, price - band),
            upper_price_per_kg=price + band,
            expected_volume_kg=max(0.0, volume),
            seasonal_volume_kg=self.seasonal_volume(target_day),
            is_actual=False,
        )

    def predict_series(
        self, horizon_days: int, as_of: date | None = None
    ) -> list[Prediction]:
        origin_day = as_of or self.trained_through
        return [
            self.predict(origin_day + timedelta(days=step), as_of=origin_day)
            for step in range(1, horizon_days + 1)
        ]

    # -- 내부 --------------------------------------------------------------

    def _origin_index(self, origin_day: date) -> int:
        for i in range(len(self.observations) - 1, -1, -1):
            if self.observations[i].date <= origin_day:
                return i
        raise ValueError(f"기준일 {origin_day} 이전의 시세 이력이 없다")

    def _band(self, horizon: int, price: float) -> float:
        std = self.residual_std_by_horizon.get(horizon)
        if std is None:
            # 학습된 지평 밖 — 가장 먼 지평의 폭을 √h 로 늘려 쓴다.
            known = self.residual_std_by_horizon
            furthest = max(known) if known else 1
            std = known.get(furthest, 0.0) * math.sqrt(horizon / max(furthest, 1))
        return max(CONFIDENCE_Z * std, MIN_RELATIVE_BAND * abs(price))


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------


def _fingerprint(observations: list[Observation]) -> str:
    """캐시 무효화용 데이터 지문 — 길이·마지막 날짜·마지막 값."""
    last = observations[-1]
    return f"{len(observations)}:{last.date.isoformat()}:{last.price_per_kg}:{last.volume_kg}"


def _seasonal_volume_by_doy(observations: list[Observation]) -> dict[int, float]:
    """day-of-year → 전후 ``SEASONAL_WINDOW_DAYS`` 일 창의 평균 거래량(평년)."""
    by_doy: dict[int, list[float]] = {}
    for observation in observations:
        by_doy.setdefault(observation.date.timetuple().tm_yday, []).append(
            float(observation.volume_kg)
        )
    smoothed: dict[int, float] = {}
    for doy in by_doy:
        window: list[float] = []
        for offset in range(-SEASONAL_WINDOW_DAYS, SEASONAL_WINDOW_DAYS + 1):
            neighbour = (doy - 1 + offset) % 365 + 1
            window.extend(by_doy.get(neighbour, ()))
        smoothed[doy] = float(np.mean(window)) if window else 0.0
    return smoothed


def train_model(session: Session, crop_id: int, region_id: int) -> PriceModel:
    """시세·거래량 모델을 학습하고 홀드아웃 백테스트까지 마친 결과를 돌려준다."""
    observations = load_observations(session, crop_id, region_id)
    if len(observations) <= max(PRICE_LAG_DAYS) + BACKTEST_DAYS:
        raise InsufficientHistoryError(
            f"crop_id={crop_id}, region_id={region_id}: 학습에 필요한 시세 이력이 부족하다 "
            f"({len(observations)}일)"
        )

    features, price_targets, volume_targets, target_dates, horizons = _supervised_frame(
        observations
    )

    # 마지막 BACKTEST_DAYS 일을 "미래" 로 취급한 홀드아웃. 기준일까지 홀드아웃
    # 구간 밖이어야 학습이 정답을 엿보지 않는다.
    cutoff = observations[-1].date - timedelta(days=BACKTEST_DAYS)
    is_holdout = np.array([d > cutoff for d in target_dates], dtype=bool)
    origin_dates = [
        target - timedelta(days=int(h)) for target, h in zip(target_dates, horizons, strict=True)
    ]
    is_train = np.array([d <= cutoff for d in origin_dates], dtype=bool) & ~is_holdout

    backtest = HistGradientBoostingRegressor(**_ESTIMATOR_PARAMS)
    backtest.fit(features[is_train], price_targets[is_train])
    holdout_predictions = backtest.predict(features[is_holdout])
    mape_pct = _mape(price_targets[is_holdout], holdout_predictions)

    residuals = price_targets[is_holdout] - holdout_predictions
    holdout_horizons = horizons[is_holdout]
    residual_std: dict[int, float] = {}
    for horizon in range(1, MAX_HORIZON_DAYS + 1):
        sample = residuals[holdout_horizons == horizon]
        if sample.size >= 2:
            residual_std[horizon] = float(np.std(sample, ddof=1))

    # 백테스트로 정확도를 확인한 뒤, 배포용 모델은 전체 데이터로 다시 학습한다.
    price_estimator = HistGradientBoostingRegressor(**_ESTIMATOR_PARAMS)
    price_estimator.fit(features, price_targets)
    volume_estimator = HistGradientBoostingRegressor(**_ESTIMATOR_PARAMS)
    volume_estimator.fit(features, volume_targets)

    logger.info(
        "price model trained crop=%s region=%s rows=%s holdout MAPE=%.2f%%",
        crop_id,
        region_id,
        features.shape[0],
        mape_pct,
    )
    return PriceModel(
        crop_id=crop_id,
        region_id=region_id,
        price_estimator=price_estimator,
        volume_estimator=volume_estimator,
        residual_std_by_horizon=residual_std,
        mape_pct=mape_pct,
        backtest_days=BACKTEST_DAYS,
        seasonal_volume_by_doy=_seasonal_volume_by_doy(observations),
        observations=observations,
        origin_matrix=_origin_features(observations)[0],
        fingerprint=_fingerprint(observations),
    )


class InsufficientHistoryError(RuntimeError):
    """학습에 쓸 시세 이력이 모자랄 때."""


# --------------------------------------------------------------------------
# Caching — 프로세스 안에서는 메모리, 재시작 사이에는 DB_PATH 옆 joblib 파일.
# --------------------------------------------------------------------------

_memo: dict[tuple[int, int], PriceModel] = {}
_memo_lock = threading.Lock()


def cache_dir() -> Path:
    """모델 캐시 디렉터리 — ``DB_PATH`` 옆의 ``models/``."""
    db_path = get_settings().db_path
    parent = Path.cwd() if db_path == ":memory:" else Path(db_path).parent
    return parent / "models"


def _cache_path(crop_id: int, region_id: int) -> Path:
    return cache_dir() / f"price_model_c{crop_id}_r{region_id}.joblib"


def get_model(
    session: Session, crop_id: int, region_id: int, *, refresh: bool = False
) -> PriceModel:
    """학습된 모델을 돌려준다 — 메모리 → 디스크 → 학습 순으로 찾는다.

    캐시는 데이터 지문으로 검증하므로, 시세가 갱신되면 자동으로 다시 학습한다.
    """
    key = (crop_id, region_id)
    with _memo_lock:
        if not refresh:
            cached = _memo.get(key)
            if cached is not None and cached.fingerprint == _current_fingerprint(
                session, crop_id, region_id
            ):
                return cached

        path = _cache_path(crop_id, region_id)
        if not refresh and path.is_file():
            try:
                model: PriceModel = joblib.load(path)
            except Exception:  # pragma: no cover - 손상된 캐시는 버리고 재학습
                logger.warning("model cache %s unreadable — retraining", path)
            else:
                if model.fingerprint == _current_fingerprint(session, crop_id, region_id):
                    _memo[key] = model
                    return model

        model = train_model(session, crop_id, region_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(model, path)
        except OSError:  # pragma: no cover - 읽기 전용 볼륨이면 메모리 캐시만
            logger.warning("could not write model cache %s", path)
        _memo[key] = model
        return model


def _current_fingerprint(session: Session, crop_id: int, region_id: int) -> str:
    observations = load_observations(session, crop_id, region_id)
    return _fingerprint(observations) if observations else ""


def clear_cache() -> None:
    """메모리 캐시를 비운다 (테스트·시세 재적재용)."""
    with _memo_lock:
        _memo.clear()
