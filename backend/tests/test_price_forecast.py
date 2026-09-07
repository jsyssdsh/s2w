"""AI 농산물 시세 예측 (SPEC 5.1) — 모델 · 서비스 · API."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.ml import price_model as ml
from app.models import Crop, Region
from app.seed import ANCHOR_DATE
from app.services import price_forecast as service

TOMATO = "토마토"
HOME_REGION = "충남 논산시"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def target_ids(seeded_session_factory: sessionmaker) -> tuple[int, int]:
    """SPEC 5.1 워크드 예제의 (토마토, 충남 논산시) ID."""
    with seeded_session_factory() as session:
        crop = session.query(Crop).filter_by(name=TOMATO).one()
        region = session.query(Region).filter_by(name=HOME_REGION).one()
        return crop.id, region.id


@pytest.fixture(scope="module")
def model(
    seeded_session_factory: sessionmaker, target_ids: tuple[int, int]
) -> ml.PriceModel:
    """모듈당 한 번만 학습한다 — 학습은 몇 초 걸린다."""
    crop_id, region_id = target_ids
    with seeded_session_factory() as session:
        return ml.train_model(session, crop_id, region_id)


@pytest.fixture
def client(seeded_session_factory: sessionmaker) -> TestClient:
    from app.db import get_session
    from app.main import app

    def override() -> Session:
        with seeded_session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# 1. 모델: 학습 · 결정론 · 백테스트 정확도
# --------------------------------------------------------------------------


def test_observations_cover_the_seeded_history(
    session: Session, target_ids: tuple[int, int]
) -> None:
    observations = ml.load_observations(session, *target_ids)

    assert len(observations) >= ml.BACKTEST_DAYS + max(ml.PRICE_LAG_DAYS)
    assert observations[-1].date == ANCHOR_DATE
    # SPEC 5.1: 기준일 토마토 시세는 2,450원/kg.
    assert observations[-1].price_per_kg == 2450
    # 기상이 실제로 조인됐다 — 조인이 실패하면 모든 행이 같은 값으로 눌린다.
    assert len({o.temp_avg for o in observations}) > 1
    assert len({o.sunshine_hours for o in observations}) > 1


def test_missing_weather_is_forward_filled(
    session: Session, target_ids: tuple[int, int]
) -> None:
    """기상 결측일이 있어도 시세 행은 버리지 않는다 (SPEC 6.2 전처리)."""
    from app.models import MarketPrice, WeatherDaily

    crop_id, region_id = target_ids
    prices = (
        session.query(MarketPrice)
        .filter_by(crop_id=crop_id, region_id=region_id)
        .count()
    )
    gap = session.query(WeatherDaily).filter_by(region_id=region_id).order_by(
        WeatherDaily.date.desc()
    ).first()
    session.delete(gap)
    session.flush()
    try:
        observations = ml.load_observations(session, crop_id, region_id)
        assert len(observations) == prices
        # 지워진 날은 직전 날의 기상을 물려받는다.
        assert observations[-1].temp_avg == observations[-2].temp_avg
    finally:
        session.rollback()


def test_training_is_deterministic_across_two_runs(
    seeded_session_factory: sessionmaker, target_ids: tuple[int, int]
) -> None:
    """SPEC 검증 조건: 같은 데이터면 두 번 학습해도 같은 숫자가 나온다."""
    crop_id, region_id = target_ids
    with seeded_session_factory() as session:
        first = ml.train_model(session, crop_id, region_id)
    with seeded_session_factory() as session:
        second = ml.train_model(session, crop_id, region_id)

    assert first.mape_pct == second.mape_pct
    assert first.fingerprint == second.fingerprint

    horizon_days = 14
    left = first.predict_series(horizon_days)
    right = second.predict_series(horizon_days)
    assert [p.date for p in left] == [p.date for p in right]
    # 부동소수점 오차 허용 없이 완전히 동일해야 한다.
    assert [p.expected_price_per_kg for p in left] == [
        p.expected_price_per_kg for p in right
    ]
    assert [p.expected_volume_kg for p in left] == [p.expected_volume_kg for p in right]
    assert [p.lower_price_per_kg for p in left] == [p.lower_price_per_kg for p in right]


def test_backtest_mape_is_under_the_documented_ceiling(model: ml.PriceModel) -> None:
    """SPEC 2.3 — 예측 정확도가 검증 가능해야 한다.

    마지막 ``BACKTEST_DAYS`` 일은 학습에서 완전히 빠진 상태로 평가된다.
    실측치는 docs/API.md 에 기록한다.
    """
    assert model.backtest_days == ml.BACKTEST_DAYS == 60
    assert 0.0 < model.mape_pct < ml.MAPE_CEILING_PCT


def test_backtest_beats_a_naive_last_value_forecast(
    session: Session, target_ids: tuple[int, int], model: ml.PriceModel
) -> None:
    """모델이 "어제 값 그대로" 보다는 나아야 학습에 의미가 있다."""
    observations = ml.load_observations(session, *target_ids)
    cutoff = observations[-1].date - timedelta(days=ml.BACKTEST_DAYS)
    by_date = {o.date: o.price_per_kg for o in observations}

    errors: list[float] = []
    for observation in observations:
        if observation.date <= cutoff:
            continue
        for horizon in range(1, ml.MAX_HORIZON_DAYS + 1):
            anchor = by_date.get(observation.date - timedelta(days=horizon))
            if anchor is not None:
                errors.append(abs(observation.price_per_kg - anchor) / observation.price_per_kg)
    naive_mape = sum(errors) / len(errors) * 100.0

    assert model.mape_pct < naive_mape


def test_feature_names_match_the_feature_matrix(
    session: Session, target_ids: tuple[int, int], model: ml.PriceModel
) -> None:
    """공개된 특징 이름 목록이 실제 학습 행렬의 열 수와 어긋나지 않는다."""
    observations = ml.load_observations(session, *target_ids)
    features, *_ = ml._supervised_frame(observations)

    assert features.shape[1] == len(model.feature_names)
    assert model.feature_names[-1] == "horizon_days"
    assert model.origin_matrix.shape[1] == len(model.feature_names) - 3


def test_predictions_stay_inside_their_confidence_band(model: ml.PriceModel) -> None:
    for prediction in model.predict_series(ml.MAX_HORIZON_DAYS):
        assert prediction.lower_price_per_kg <= prediction.expected_price_per_kg
        assert prediction.expected_price_per_kg <= prediction.upper_price_per_kg
        assert prediction.lower_price_per_kg >= 0.0
        assert prediction.expected_volume_kg >= 0.0


def test_horizon_zero_returns_the_observed_price(model: ml.PriceModel) -> None:
    """비교표의 기준 행은 예측이 아니라 실제 시세여야 한다."""
    prediction = model.predict(ANCHOR_DATE)

    assert prediction.is_actual is True
    assert prediction.horizon_days == 0
    assert prediction.expected_price_per_kg == 2450.0
    assert prediction.lower_price_per_kg == prediction.upper_price_per_kg == 2450.0


def test_model_rejects_out_of_range_targets(model: ml.PriceModel) -> None:
    with pytest.raises(ValueError):
        model.predict(ANCHOR_DATE - timedelta(days=1))
    with pytest.raises(ValueError):
        model.predict(ANCHOR_DATE + timedelta(days=ml.MAX_HORIZON_DAYS + 1))


def test_training_needs_enough_history(
    session: Session, target_ids: tuple[int, int]
) -> None:
    crop_id, _region_id = target_ids
    # 시드는 시세를 홈 지역에만 넣는다 — 다른 지역은 이력이 없다.
    empty_region = next(
        r.id
        for r in session.query(Region).all()
        if r.id not in service.available_region_ids(session, crop_id)
    )
    with pytest.raises(ml.InsufficientHistoryError):
        ml.train_model(session, crop_id, empty_region)

    # 서비스는 이 경우를 404 로 바꾸면서 쓸 수 있는 지역을 알려 준다.
    with pytest.raises(service.UnknownTargetError, match="region_id"):
        service.price_forecast(session, crop_id=crop_id, region_id=empty_region)


def test_model_cache_round_trips_through_disk(
    seeded_session_factory: sessionmaker, target_ids: tuple[int, int]
) -> None:
    """디스크 캐시에서 되살린 모델이 새로 학습한 모델과 같은 값을 낸다."""
    crop_id, region_id = target_ids
    ml.clear_cache()
    with seeded_session_factory() as session:
        trained = ml.get_model(session, crop_id, region_id, refresh=True)
    assert ml.cache_dir().is_dir()

    ml.clear_cache()  # 메모리를 비워 디스크 경로를 강제한다
    with seeded_session_factory() as session:
        restored = ml.get_model(session, crop_id, region_id)

    assert restored.fingerprint == trained.fingerprint
    assert restored.mape_pct == trained.mape_pct
    assert [p.expected_price_per_kg for p in restored.predict_series(7)] == [
        p.expected_price_per_kg for p in trained.predict_series(7)
    ]


# --------------------------------------------------------------------------
# 2. 판정 규칙 — SPEC 5.1 의 두 라벨 열
# --------------------------------------------------------------------------


def test_supply_outlook_thresholds() -> None:
    norm = 10_000.0
    assert service.supply_outlook(norm * 0.90, norm) == service.SUPPLY_DECREASE
    assert service.supply_outlook(norm, norm) == service.SUPPLY_NORMAL
    assert service.supply_outlook(norm * 1.10, norm) == service.SUPPLY_INCREASE
    # 평년 자료가 없으면 판단하지 않는다.
    assert service.supply_outlook(norm, 0.0) == service.SUPPLY_NORMAL


def test_guidance_thresholds_match_the_spec_table() -> None:
    # 기준 행 (변동 0) — SPEC 8월 8일
    assert service.guidance_for(0.0) == service.GUIDANCE_SHIP_NOW
    # 약 5.3% 상승 — SPEC 8월 10일
    assert service.guidance_for(5.3) == service.GUIDANCE_HOLD
    # 약 5.3% 하락 — SPEC 8월 17일
    assert service.guidance_for(-5.3) == service.GUIDANCE_SHIP_EARLY
    # -3% 는 경계값이라 아직 조기 출하가 아니다.
    assert service.guidance_for(service.GUIDANCE_FALLING_PCT) == service.GUIDANCE_SHIP_NOW
    assert service.guidance_for(-3.01) == service.GUIDANCE_SHIP_EARLY


# --------------------------------------------------------------------------
# 3. 서비스: 출하일 비교표
# --------------------------------------------------------------------------


def test_shipping_window_reproduces_the_spec_table_shape(
    session: Session, target_ids: tuple[int, int]
) -> None:
    """SPEC 5.1 "토마토 1,000kg 출하일 결정 비교" 3열 표."""
    crop_id, region_id = target_ids
    candidates = [ANCHOR_DATE, ANCHOR_DATE + timedelta(days=2), ANCHOR_DATE + timedelta(days=9)]

    result = service.shipping_window(
        session, crop_id=crop_id, region_id=region_id, qty_kg=1000,
        candidate_dates=candidates,
    )

    assert [row.date for row in result.rows] == candidates
    assert result.baseline_date == ANCHOR_DATE
    assert result.qty_kg == 1000
    assert result.as_of == ANCHOR_DATE

    baseline, *rest = result.rows
    # 기준 행: 실제 시세 2,450원/kg × 1,000kg = 245만 원, 변동 0%.
    assert baseline.is_baseline is True
    assert baseline.horizon_days == 0
    assert baseline.expected_price_per_kg == 2450
    assert baseline.expected_revenue_krw == 2_450_000
    assert baseline.change_pct_vs_baseline == 0.0
    assert baseline.guidance == service.GUIDANCE_SHIP_NOW

    for row in rest:
        assert row.is_baseline is False
        assert row.horizon_days > 0
        assert row.supply_outlook in {
            service.SUPPLY_DECREASE, service.SUPPLY_NORMAL, service.SUPPLY_INCREASE
        }
        assert row.guidance in {
            service.GUIDANCE_SHIP_NOW, service.GUIDANCE_HOLD, service.GUIDANCE_SHIP_EARLY
        }


def test_shipping_window_baseline_math(
    session: Session, target_ids: tuple[int, int]
) -> None:
    """매출 = 예상 단가 × 물량, 변동률 = 기준 대비 — 두 식이 행마다 성립한다."""
    crop_id, region_id = target_ids
    qty_kg = 1000
    result = service.shipping_window(
        session, crop_id=crop_id, region_id=region_id, qty_kg=qty_kg,
        candidate_dates=[ANCHOR_DATE + timedelta(days=d) for d in (1, 5, 12)],
    )

    baseline = result.rows[0]
    for row in result.rows:
        assert row.expected_revenue_krw == pytest.approx(
            row.expected_price_per_kg * qty_kg, rel=1e-3
        )
        expected_change = (
            (row.expected_price_per_kg - baseline.expected_price_per_kg)
            / baseline.expected_price_per_kg
            * 100.0
        )
        assert row.change_pct_vs_baseline == pytest.approx(expected_change, abs=0.05)
        assert row.guidance == service.guidance_for(row.change_pct_vs_baseline)


def test_shipping_window_deduplicates_and_keeps_input_order(
    session: Session, target_ids: tuple[int, int]
) -> None:
    crop_id, region_id = target_ids
    later = ANCHOR_DATE + timedelta(days=7)
    result = service.shipping_window(
        session, crop_id=crop_id, region_id=region_id, qty_kg=500,
        candidate_dates=[later, ANCHOR_DATE, later],
    )

    assert [row.date for row in result.rows] == [later, ANCHOR_DATE]
    assert result.baseline_date == later


def test_shipping_window_validates_inputs(
    session: Session, target_ids: tuple[int, int]
) -> None:
    crop_id, region_id = target_ids
    kwargs = dict(crop_id=crop_id, region_id=region_id, qty_kg=1000)

    with pytest.raises(service.ForecastRangeError):
        service.shipping_window(session, candidate_dates=[], **kwargs)
    with pytest.raises(service.ForecastRangeError):
        service.shipping_window(
            session, candidate_dates=[ANCHOR_DATE - timedelta(days=1)], **kwargs
        )
    with pytest.raises(service.ForecastRangeError):
        service.shipping_window(
            session,
            candidate_dates=[ANCHOR_DATE + timedelta(days=ml.MAX_HORIZON_DAYS + 1)],
            **kwargs,
        )
    with pytest.raises(service.ForecastRangeError):
        service.shipping_window(
            session, crop_id=crop_id, region_id=region_id, qty_kg=0,
            candidate_dates=[ANCHOR_DATE],
        )
    with pytest.raises(service.UnknownTargetError):
        service.shipping_window(
            session, crop_id=9999, region_id=region_id, qty_kg=1,
            candidate_dates=[ANCHOR_DATE],
        )


def test_price_forecast_service_shape(
    session: Session, target_ids: tuple[int, int]
) -> None:
    crop_id, region_id = target_ids
    result = service.price_forecast(
        session, crop_id=crop_id, region_id=region_id, horizon=14
    )

    assert result.crop_name == TOMATO
    assert result.region_name == HOME_REGION
    assert result.as_of == ANCHOR_DATE
    assert len(result.forecast) == 14
    assert [p.date for p in result.forecast] == [
        ANCHOR_DATE + timedelta(days=d) for d in range(1, 15)
    ]
    assert [p.horizon_days for p in result.forecast] == list(range(1, 15))
    # 차트에 붙일 최근 실적이 기준일에서 끝난다.
    assert result.actuals[-1].date == ANCHOR_DATE
    assert result.actuals[-1].price_per_kg == 2450
    assert len(result.actuals) == service.DEFAULT_ACTUAL_DAYS
    assert result.model.mape_pct < ml.MAPE_CEILING_PCT


def test_price_forecast_honours_as_of(
    session: Session, target_ids: tuple[int, int]
) -> None:
    """as_of 를 과거로 옮기면 예측 구간 전체가 그만큼 앞으로 온다 (결정론)."""
    crop_id, region_id = target_ids
    as_of = ANCHOR_DATE - timedelta(days=30)
    result = service.price_forecast(
        session, crop_id=crop_id, region_id=region_id, horizon=5, as_of=as_of
    )

    assert result.as_of == as_of
    assert result.forecast[0].date == as_of + timedelta(days=1)
    assert result.actuals[-1].date == as_of

    with pytest.raises(service.ForecastRangeError):
        service.price_forecast(
            session, crop_id=crop_id, region_id=region_id,
            as_of=ANCHOR_DATE + timedelta(days=1),
        )


# --------------------------------------------------------------------------
# 4. API
# --------------------------------------------------------------------------


def test_get_price_forecast_endpoint(
    client: TestClient, target_ids: tuple[int, int]
) -> None:
    crop_id, region_id = target_ids
    response = client.get(
        "/api/forecast/price",
        params={"crop_id": crop_id, "region_id": region_id, "horizon": 14},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["crop_name"] == TOMATO
    assert body["as_of"] == ANCHOR_DATE.isoformat()
    assert body["horizon_days"] == 14
    assert len(body["forecast"]) == 14
    assert body["actuals"][-1]["price_per_kg"] == 2450

    first = body["forecast"][0]
    assert first["date"] == (ANCHOR_DATE + timedelta(days=1)).isoformat()
    assert first["lower_price_per_kg"] <= first["expected_price_per_kg"]
    assert first["expected_price_per_kg"] <= first["upper_price_per_kg"]
    assert first["supply_outlook"] in {
        service.SUPPLY_DECREASE, service.SUPPLY_NORMAL, service.SUPPLY_INCREASE
    }
    assert 0.0 < body["model"]["mape_pct"] < ml.MAPE_CEILING_PCT
    assert body["model"]["backtest_days"] == ml.BACKTEST_DAYS


def test_get_price_forecast_rejects_bad_input(
    client: TestClient, target_ids: tuple[int, int]
) -> None:
    crop_id, region_id = target_ids
    base = {"crop_id": crop_id, "region_id": region_id}

    assert client.get("/api/forecast/price", params={**base, "horizon": 0}).status_code == 422
    assert (
        client.get(
            "/api/forecast/price", params={**base, "horizon": ml.MAX_HORIZON_DAYS + 1}
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/forecast/price", params={"crop_id": 9999, "region_id": region_id}
        ).status_code
        == 404
    )


def test_post_shipping_window_endpoint(
    client: TestClient, target_ids: tuple[int, int]
) -> None:
    """SPEC 5.1 비교표: 후보 3일 → 3행, 첫 행이 기준."""
    crop_id, region_id = target_ids
    candidates = [
        ANCHOR_DATE.isoformat(),
        (ANCHOR_DATE + timedelta(days=2)).isoformat(),
        (ANCHOR_DATE + timedelta(days=9)).isoformat(),
    ]
    response = client.post(
        "/api/forecast/shipping-window",
        json={
            "crop_id": crop_id,
            "region_id": region_id,
            "qty_kg": 1000,
            "candidate_dates": candidates,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["qty_kg"] == 1000
    assert body["baseline_date"] == candidates[0]
    assert [row["date"] for row in body["rows"]] == candidates

    baseline = body["rows"][0]
    assert baseline["is_baseline"] is True
    assert baseline["expected_price_per_kg"] == 2450
    assert baseline["expected_revenue_krw"] == 2_450_000
    assert baseline["change_pct_vs_baseline"] == 0.0
    assert baseline["guidance"] == service.GUIDANCE_SHIP_NOW

    for row in body["rows"]:
        assert row["expected_revenue_krw"] == pytest.approx(
            row["expected_price_per_kg"] * 1000, rel=1e-3
        )
        assert row["guidance"] == service.guidance_for(row["change_pct_vs_baseline"])


def test_post_shipping_window_rejects_bad_input(
    client: TestClient, target_ids: tuple[int, int]
) -> None:
    crop_id, region_id = target_ids
    body = {"crop_id": crop_id, "region_id": region_id, "qty_kg": 1000}

    # 빈 후보 목록 / 음수 물량 — Pydantic 이 막는다.
    assert client.post(
        "/api/forecast/shipping-window", json={**body, "candidate_dates": []}
    ).status_code == 422
    assert client.post(
        "/api/forecast/shipping-window",
        json={**body, "qty_kg": 0, "candidate_dates": [ANCHOR_DATE.isoformat()]},
    ).status_code == 422

    # 지평을 넘어선 후보일 — 서비스가 막는다.
    too_far = (ANCHOR_DATE + timedelta(days=ml.MAX_HORIZON_DAYS + 1)).isoformat()
    assert client.post(
        "/api/forecast/shipping-window", json={**body, "candidate_dates": [too_far]}
    ).status_code == 422

    # 시세 이력이 없는 지역.
    with_no_history = client.post(
        "/api/forecast/shipping-window",
        json={
            "crop_id": crop_id,
            "region_id": _region_without_prices(client, crop_id),
            "qty_kg": 1000,
            "candidate_dates": [ANCHOR_DATE.isoformat()],
        },
    )
    assert with_no_history.status_code == 404


def _region_without_prices(client: TestClient, crop_id: int) -> int:
    """시세 이력이 없는 지역 ID — 시드는 홈 지역에만 시세를 넣는다."""
    regions = client.get("/api/regions").json()
    for region in regions:
        probe = client.get(
            "/api/forecast/price",
            params={"crop_id": crop_id, "region_id": region["id"], "horizon": 1},
        )
        if probe.status_code == 404:
            return region["id"]
    raise AssertionError("모든 지역에 시세 이력이 있다 — 404 경로를 시험할 수 없다")
