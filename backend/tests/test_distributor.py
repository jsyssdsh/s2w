"""SPEC 4.3 — 유통업체 대시보드."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Deal, DealStatus, Grade, Shipment, Wholesaler
from app.seed import ANCHOR_DATE
from app.services import distributor as service


@pytest.fixture
def scratch_factory(tmp_path: Path) -> sessionmaker:
    """쓰기가 있는 테스트용 일회용 DB — 세션 공유 시드를 더럽히지 않는다."""
    from app.db import build_engine, create_all
    from app.seed import seed_all

    engine = build_engine(str(tmp_path / "scratch.db"))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        seed_all(s)
        s.commit()
    return factory


@pytest.fixture
def client(seeded_session_factory: sessionmaker) -> Iterator[TestClient]:
    from app.db import get_session
    from app.main import app

    def override() -> Iterator[Session]:
        with seeded_session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def write_client(scratch_factory: sessionmaker) -> Iterator[TestClient]:
    from app.db import get_session
    from app.main import app

    def override() -> Iterator[Session]:
        with scratch_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _wholesaler(session: Session, name: str) -> Wholesaler:
    return session.scalars(select(Wholesaler).where(Wholesaler.name == name)).one()


# --------------------------------------------------------------------------
# 도매처 목록
# --------------------------------------------------------------------------


def test_wholesaler_list_carries_inventory_lot_count(client: TestClient) -> None:
    """대시보드는 재고를 가진 도매처를 기본으로 고른다 — 그 신호가 응답에 있어야 한다."""
    rows = client.get("/api/distributor/wholesalers").json()
    assert [r["name"] for r in rows] == ["A 청과도매", "B 농산물유통", "C 도매시장"]

    by_name = {r["name"]: r for r in rows}
    # SPEC 5.3 의 토마토 1,700kg + 양파 8톤 재고는 B 가 들고 있다.
    assert by_name["B 농산물유통"]["inventory_lot_count"] == 5
    assert by_name["A 청과도매"]["inventory_lot_count"] == 0


# --------------------------------------------------------------------------
# AI 추천 농가 리스트
# --------------------------------------------------------------------------


def test_recommendations_cover_every_open_shipment_in_window(client: TestClient) -> None:
    """시드의 토마토 1건 + 양파 4건이 모두 공급 가능 건수로 잡힌다."""
    body = client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 2}
    ).json()

    assert body["as_of"] == ANCHOR_DATE.isoformat()
    assert body["summary"]["supply_count"] == 5
    assert body["summary"]["supply_qty_kg"] == 1000 + 4 * 30_000
    assert {r["crop_name"] for r in body["rows"]} == {"토마토", "양파"}


def test_spec_4_3_columns_are_all_present(client: TestClient) -> None:
    """SPEC 4.3 향후 수정 계획의 여섯 열 + 권장 거래가가 한 줄에 다 있다."""
    body = client.get(
        "/api/distributor/farm-recommendations",
        params={"wholesaler_id": 2, "crop_id": 1},
    ).json()
    row = body["rows"][0]

    assert row["crop_name"] == "토마토"
    assert row["grade_label"] == "특상품"          # 품질 등급
    assert row["qty_kg"] == 1000                   # 공급량
    assert row["distance_km"] == pytest.approx(40.0, abs=0.1)   # 농가별 거리
    assert row["transport_cost_krw"] == 80_000     # 운송비 = 40km × 2,000원
    assert row["recommended_price_per_kg"] > 0     # 권장 거래가
    assert row["expected_net_profit_krw"] > 0      # 예상 순수익
    assert row["reason"]                           # 추천 이유


def test_net_profit_follows_the_architecture_formula(client: TestClient) -> None:
    """예상 순수익 = 판매금액 − 수수료 − 매입금액 − 운송비 (ARCHITECTURE 5절)."""
    body = client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 2}
    ).json()

    for row in body["rows"]:
        assert row["resale_revenue_krw"] == row["graded_price_per_kg"] * row["purchasable_kg"]
        assert row["purchase_cost_krw"] == (
            row["recommended_price_per_kg"] * row["purchasable_kg"]
        )
        assert row["expected_net_profit_krw"] == (
            row["resale_revenue_krw"]
            - row["fee_krw"]
            - row["purchase_cost_krw"]
            - row["transport_cost_krw"]
        )
        # 권장 거래가는 목표 마진을 남기도록 역산한 값이다.
        assert row["margin_pct"] == pytest.approx(
            service.TARGET_MARGIN_RATE * 100, abs=0.5
        )


def test_purchasable_is_capped_by_wholesaler_capacity(client: TestClient) -> None:
    """양파 30톤 출하도 도매처 구매 가능량(1,000kg)까지만 매입 대상이다."""
    body = client.get(
        "/api/distributor/farm-recommendations",
        params={"wholesaler_id": 2, "crop_id": 2},
    ).json()

    for row in body["rows"]:
        assert row["qty_kg"] == 30_000
        assert row["purchasable_kg"] == 1000
        assert row["unsold_kg"] == 29_000


def test_transport_cost_decides_which_rows_are_recommended(client: TestClient) -> None:
    """운송비가 비쌀수록 권장 거래가가 내려가고, 하한선 아래는 추천에서 빠진다.

    같은 양파 출하라도 40km 의 B 는 추천이고, 60km·70km 의 A·C 는 아니다 —
    운송비는 물량에 상관없이 한 번 드는 값이라 값싼 품목일수록 크게 먹는다.
    """
    onion = {"crop_id": 2}
    near = client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 2, **onion}
    ).json()
    far = client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 3, **onion}
    ).json()

    assert all(r["recommended"] for r in near["rows"])
    assert not any(r["recommended"] for r in far["rows"])
    assert near["rows"][0]["recommended_price_per_kg"] > far["rows"][0]["recommended_price_per_kg"]
    assert near["rows"][0]["offer_pct"] >= service.VIABLE_OFFER_RATIO * 100
    assert far["rows"][0]["offer_pct"] < service.VIABLE_OFFER_RATIO * 100

    # 토마토는 값이 비싸 같은 70km 에서도 운송비를 감당한다.
    tomato_far = client.get(
        "/api/distributor/farm-recommendations",
        params={"wholesaler_id": 3, "crop_id": 1},
    ).json()
    assert tomato_far["rows"][0]["recommended"] is True


def test_recommended_rows_come_first_and_sort_by_net_profit(client: TestClient) -> None:
    body = client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 1}
    ).json()
    flags = [r["recommended"] for r in body["rows"]]
    assert flags == sorted(flags, reverse=True)

    picked = [r["expected_net_profit_krw"] for r in body["rows"] if r["recommended"]]
    assert picked == sorted(picked, reverse=True)

    summary = body["summary"]
    assert summary["recommended_count"] == len(picked)
    assert summary["expected_net_profit_krw"] == sum(picked)


def test_grade_lifts_the_expected_sale_price(client: TestClient) -> None:
    """등급 계수가 예상 판매단가에 그대로 반영된다 (특상품 = 시세의 110%)."""
    body = client.get(
        "/api/distributor/farm-recommendations",
        params={"wholesaler_id": 2, "crop_id": 1},
    ).json()
    row = body["rows"][0]
    assert row["graded_price_per_kg"] == round(
        row["market_price_per_kg"] * service.GRADE_PRICE_FACTOR[Grade.SPECIAL]
    )


def test_settled_shipments_drop_out_of_the_list(
    scratch_factory: sessionmaker, write_client: TestClient
) -> None:
    """거래가 확정된 출하는 더 이상 매입 대상이 아니다."""
    before = write_client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 2}
    ).json()
    target = before["rows"][0]["shipment_id"]

    with scratch_factory() as s:
        deal = s.scalars(
            select(Deal).where(Deal.shipment_id == target)
        ).first()
        if deal is None:
            deal = Deal(shipment_id=target, wholesaler_id=2, agreed_price_krw=1)
            s.add(deal)
        deal.status = DealStatus.SETTLED
        s.commit()

    after = write_client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 2}
    ).json()
    assert target not in {r["shipment_id"] for r in after["rows"]}
    assert after["summary"]["supply_count"] == before["summary"]["supply_count"] - 1


def test_window_days_bounds_the_list(client: TestClient) -> None:
    """창을 좁히면 뒤쪽 출하가 빠진다 — 양파는 기준일 +3/+7/+11/+15 일이다."""
    body = client.get(
        "/api/distributor/farm-recommendations",
        params={"wholesaler_id": 2, "window_days": 5},
    ).json()
    assert body["summary"]["supply_count"] == 2  # 토마토(당일) + 양파(+3일)
    assert body["window_end"] == "2026-08-13"


def test_unknown_ids_are_404(client: TestClient) -> None:
    assert (
        client.get(
            "/api/distributor/farm-recommendations", params={"wholesaler_id": 9999}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/distributor/farm-recommendations",
            params={"wholesaler_id": 2, "crop_id": 9999},
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------
# 거래 요청 보내기
# --------------------------------------------------------------------------


def test_deal_request_writes_a_proposed_deal(
    scratch_factory: sessionmaker, write_client: TestClient
) -> None:
    with scratch_factory() as s:
        onion = s.scalars(
            select(Shipment)
            .where(Shipment.crop_id == 2)
            .order_by(Shipment.ship_date)
        ).first()
        assert onion is not None
        shipment_id = onion.id

    response = write_client.post(
        "/api/distributor/deal-requests",
        json={"wholesaler_id": 2, "shipment_id": shipment_id},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["status"] == DealStatus.PROPOSED.value
    assert body["qty_kg"] == 1000                       # 구매 가능량까지
    assert body["agreed_price_krw"] == body["unit_price_krw"] * body["qty_kg"]
    assert "거래 요청을 보냈습니다" in body["message"]

    with scratch_factory() as s:
        deals = s.scalars(
            select(Deal).where(
                Deal.shipment_id == shipment_id, Deal.wholesaler_id == 2
            )
        ).all()
        assert len(deals) == 1

    # 리스트에도 "요청함" 으로 되돌아온다.
    rows = write_client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 2}
    ).json()["rows"]
    assert next(r for r in rows if r["shipment_id"] == shipment_id)["requested"] is True


def test_deal_request_is_idempotent(
    scratch_factory: sessionmaker, write_client: TestClient
) -> None:
    with scratch_factory() as s:
        shipment_id = s.scalars(
            select(Shipment).where(Shipment.crop_id == 2).order_by(Shipment.id)
        ).first().id

    payload = {"wholesaler_id": 2, "shipment_id": shipment_id}
    first = write_client.post("/api/distributor/deal-requests", json=payload).json()
    second = write_client.post("/api/distributor/deal-requests", json=payload).json()

    assert first["created"] is True
    assert second["created"] is False
    assert first["id"] == second["id"]

    with scratch_factory() as s:
        count = len(
            s.scalars(
                select(Deal).where(
                    Deal.shipment_id == shipment_id, Deal.wholesaler_id == 2
                )
            ).all()
        )
    assert count == 1


def test_explicit_unit_price_wins(
    scratch_factory: sessionmaker, write_client: TestClient
) -> None:
    with scratch_factory() as s:
        shipment_id = s.scalars(
            select(Shipment).where(Shipment.crop_id == 2).order_by(Shipment.id)
        ).first().id

    body = write_client.post(
        "/api/distributor/deal-requests",
        json={"wholesaler_id": 2, "shipment_id": shipment_id, "unit_price_krw": 1234},
    ).json()
    assert body["unit_price_krw"] == 1234
    assert body["agreed_price_krw"] == 1234 * body["qty_kg"]


def test_deal_request_on_a_settled_shipment_is_409(
    scratch_factory: sessionmaker, write_client: TestClient
) -> None:
    with scratch_factory() as s:
        shipment_id = s.scalars(
            select(Shipment).where(Shipment.crop_id == 2).order_by(Shipment.id)
        ).first().id
        s.add(
            Deal(
                shipment_id=shipment_id,
                wholesaler_id=1,
                agreed_price_krw=1,
                status=DealStatus.SETTLED,
            )
        )
        s.commit()

    response = write_client.post(
        "/api/distributor/deal-requests",
        json={"wholesaler_id": 2, "shipment_id": shipment_id},
    )
    assert response.status_code == 409


def test_deal_request_unknown_ids_are_404(write_client: TestClient) -> None:
    assert (
        write_client.post(
            "/api/distributor/deal-requests",
            json={"wholesaler_id": 9999, "shipment_id": 1},
        ).status_code
        == 404
    )
    assert (
        write_client.post(
            "/api/distributor/deal-requests",
            json={"wholesaler_id": 2, "shipment_id": 9999},
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------
# 실시간 시장 분석
# --------------------------------------------------------------------------


def test_market_snapshot_covers_every_seeded_crop(client: TestClient) -> None:
    body = client.get("/api/distributor/market").json()

    assert body["region_name"] == "충남 논산시"
    assert body["as_of"] == ANCHOR_DATE.isoformat()
    assert [r["crop_name"] for r in body["rows"]] == [
        "토마토",
        "양파",
        "딸기",
        "오이",
        "배추",
    ]


def test_market_rows_report_price_and_demand_change(client: TestClient) -> None:
    """SPEC 4.3 "품목별 가격/수요 등락률" — 기준일 실적을 며칠 전과 견준다."""
    body = client.get("/api/distributor/market", params={"lookback_days": 7}).json()
    tomato = next(r for r in body["rows"] if r["crop_name"] == "토마토")

    # SPEC 5.1 워크드 예제: 기준일 토마토 시세는 2,450원/kg.
    assert tomato["price_per_kg"] == 2450
    assert tomato["price_change_pct"] == pytest.approx(
        (2450 - tomato["previous_price_per_kg"]) / tomato["previous_price_per_kg"] * 100,
        abs=0.01,
    )
    assert tomato["demand_change_pct"] == pytest.approx(
        (tomato["volume_kg"] - tomato["previous_volume_kg"])
        / tomato["previous_volume_kg"]
        * 100,
        abs=0.01,
    )
    assert tomato["trend"] == service.market_trend(tomato["price_change_pct"])


def test_market_trend_labels_follow_the_flat_band() -> None:
    assert service.market_trend(0.0) == service.MARKET_TREND_FLAT
    assert service.market_trend(service.MARKET_FLAT_PCT) == service.MARKET_TREND_FLAT
    assert service.market_trend(service.MARKET_FLAT_PCT + 0.1) == service.MARKET_TREND_UP
    assert (
        service.market_trend(-service.MARKET_FLAT_PCT - 0.1) == service.MARKET_TREND_DOWN
    )


def test_market_series_is_the_recent_actuals(client: TestClient) -> None:
    """차트는 기준일까지의 실적 구간을 그대로 쓴다."""
    body = client.get("/api/distributor/market").json()
    series = body["rows"][0]["series"]

    assert len(series) == service.MARKET_SERIES_DAYS
    assert [p["date"] for p in series] == sorted(p["date"] for p in series)
    assert series[-1]["date"] == body["as_of"]
    assert series[-1]["price_per_kg"] == body["rows"][0]["price_per_kg"]


def test_market_is_deterministic(client: TestClient) -> None:
    """같은 요청은 같은 숫자를 낸다 (ARCHITECTURE 6절)."""
    first = client.get("/api/distributor/market").json()
    second = client.get("/api/distributor/market").json()
    assert first == second


def test_market_does_not_train_a_price_model(client: TestClient) -> None:
    """대시보드 첫 그림이 SPEC 5.1 모델 학습을 기다리게 두지 않는다.

    학습은 캐시가 비어 있을 때 품목당 수십 초가 걸린다. 이 패널은 실측
    시세만 읽으므로 예측 엔진을 부르지 않아야 한다.
    """
    calls: list[tuple[int, int]] = []
    original = service.price_forecast.price_forecast

    def spy(session, *, crop_id, region_id, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((crop_id, region_id))
        return original(session, crop_id=crop_id, region_id=region_id, **kwargs)

    service.price_forecast.price_forecast = spy  # type: ignore[assignment]
    try:
        assert client.get("/api/distributor/market").status_code == 200
        assert (
            client.get(
                "/api/distributor/farm-recommendations", params={"wholesaler_id": 2}
            ).status_code
            == 200
        )
    finally:
        service.price_forecast.price_forecast = original  # type: ignore[assignment]
    assert calls == []


def test_use_forecast_switches_the_reference_price(client: TestClient) -> None:
    """``use_forecast`` 를 켜면 SPEC 5.1 예측 시세가 기준 단가가 된다."""
    default = client.get(
        "/api/distributor/farm-recommendations", params={"wholesaler_id": 2}
    ).json()
    assert {r["price_source"] for r in default["rows"]} == {
        service.PRICE_SOURCE_MARKET
    }

    forecast = client.get(
        "/api/distributor/farm-recommendations",
        params={"wholesaler_id": 2, "use_forecast": "true"},
    ).json()
    assert {r["price_source"] for r in forecast["rows"]} == {
        service.PRICE_SOURCE_FORECAST
    }
    # 출하일마다 예측이 다르므로 같은 품목의 기준 단가가 갈린다.
    onion = [r["market_price_per_kg"] for r in forecast["rows"] if r["crop_name"] == "양파"]
    assert len(set(onion)) > 1


def test_market_unknown_region_is_404(client: TestClient) -> None:
    assert client.get("/api/distributor/market", params={"region_id": 9999}).status_code == 404
