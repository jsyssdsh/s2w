"""도매처 추천 (SPEC 5.2) 과 거래 피드백 루프 (SPEC 7.1).

SPEC 5.2 표에 대한 주의 — A 행의 "예상 순수익 239만 5,000원" 은 표 자체와
맞지 않는다. 같은 행의 단가·구매량·운송비로는 수수료를 0 으로 놓아도
2,550원 × 1,000kg − 18만원 = 237만원 이 상한이라 239만 5,000원 이 나올 수 없다.
수수료 3% 를 적용한 실제 값은 **229만 3,500원** 이고, SPEC 의 숫자는 이 값의
자릿수가 뒤바뀐 오기로 보인다. B(242만 2,600원) 와 C(188만 5,200원) 는 SPEC 과
정확히 일치하며, SPEC 이 실제로 요구하는 결론인 **순위 B > A > C** 도 그대로다.
docs/ARCHITECTURE.md 도 이 기능의 계약을 금액이 아니라 순위로 적어 두었다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Crop, Deal, DealStatus, Farm, Region, Shipment, Wholesaler
from app.seed import ANCHOR_DATE
from app.services import wholesaler_rec as service

# SPEC 5.2 활용 예시: 토마토 1,000kg.
OFFERED_KG = 1000

# 실제 계산값. B·C 는 SPEC 표와 일치, A 는 위 docstring 참고.
EXPECTED_NET_KRW = {
    "B 농산물유통": 2_422_600,
    "A 청과도매": 2_293_500,
    "C 도매시장": 1_885_200,
}


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


@pytest.fixture
def scratch_session(tmp_path) -> Session:
    """쓰기 테스트용 별도 DB — 세션 공용 시드 DB 를 더럽히지 않는다."""
    from app.db import build_engine, create_all
    from app.seed import seed_all

    engine = build_engine(str(tmp_path / "deals.db"))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        seed_all(s)
    with factory() as s:
        yield s


def _tomato_farm(session: Session) -> tuple[Farm, Crop]:
    crop = session.scalar(select(Crop).where(Crop.name == "토마토"))
    farm = session.scalar(select(Farm).where(Farm.name == "울퉁불퉁 청년농장"))
    return farm, crop


def _recommend(session: Session, qty_kg: int = OFFERED_KG, **kwargs):
    farm, crop = _tomato_farm(session)
    return service.recommend_wholesalers(
        session,
        farm_id=farm.id,
        crop_id=crop.id,
        qty_kg=qty_kg,
        ship_date=ANCHOR_DATE,
        **kwargs,
    )


# --------------------------------------------------------------------------
# SPEC 5.2 워크드 예제
# --------------------------------------------------------------------------


def test_spec_5_2_ranking_and_net_profit(session: Session) -> None:
    """B 1위 · A 2위 · C 3위, 금액은 표의 값 (A 는 오기 보정)."""
    result = _recommend(session)

    assert [c.name for c in result.candidates] == [
        "B 농산물유통",
        "A 청과도매",
        "C 도매시장",
    ]
    assert [c.rank for c in result.candidates] == [1, 2, 3]
    for candidate in result.candidates:
        assert round(candidate.net_profit_krw) == pytest.approx(
            EXPECTED_NET_KRW[candidate.name], abs=1
        )


def test_spec_5_2_breakdown_matches_the_table(session: Session) -> None:
    """단가·구매량·운송비 열이 그대로 분해되어 나온다."""
    by_name = {c.name: c for c in _recommend(session).candidates}

    expected = {
        # name: (단가, 구매량, 운송비, 거리 km)
        "A 청과도매": (2550, 1000, 180_000, 60.0),
        "B 농산물유통": (2580, 1000, 80_000, 40.0),
        "C 도매시장": (2700, 800, 210_000, 70.0),
    }
    for name, (unit_price, sellable, transport, distance) in expected.items():
        c = by_name[name]
        assert c.unit_price_krw == unit_price
        assert c.sellable_kg == sellable
        assert round(c.transport_cost_krw) == pytest.approx(transport, abs=1)
        assert c.distance_km == pytest.approx(distance, abs=0.01)
        # 판매금액 − 운송비 − 수수료 라는 정의가 실제로 지켜지는지.
        assert c.gross_krw == pytest.approx(unit_price * sellable)
        assert c.net_profit_krw == pytest.approx(
            c.gross_krw - c.transport_cost_krw - c.fee_krw
        )


def test_capacity_caps_the_sellable_quantity(session: Session) -> None:
    """구매 가능량을 넘는 물량은 판매금액에 들어가지 않고 잔여로 남는다."""
    c = {x.name: x for x in _recommend(session).candidates}["C 도매시장"]

    assert c.capacity_kg == 800
    assert c.sellable_kg == 800
    assert c.unsold_kg == 200
    assert c.gross_krw == pytest.approx(2700 * 800)
    # 단가는 가장 높은데도 3위 — SPEC 5.2 의 "필요성" 문단이 말하는 상황.
    assert c.rank == 3
    assert "200kg 이 남습니다" in c.reason


def test_capacity_is_not_capped_below_the_offer(session: Session) -> None:
    """출하량이 구매 가능량보다 적으면 전량 매입되고 잔여가 없다."""
    result = _recommend(session, qty_kg=500)
    for c in result.candidates:
        assert c.sellable_kg == 500
        assert c.unsold_kg == 0


def test_fee_is_a_share_of_the_gross(session: Session) -> None:
    """수수료 = 판매금액 × 수수료율. 시드는 세 곳 모두 3%."""
    for c in _recommend(session).candidates:
        assert c.fee_rate == pytest.approx(0.03)
        assert c.fee_krw == pytest.approx(c.gross_krw * 0.03)
    b = {x.name: x for x in _recommend(session).candidates}["B 농산물유통"]
    assert round(b.fee_krw) == 77_400


def test_transport_cost_scales_with_distance(session: Session) -> None:
    """운송비 = haversine 거리 × km당 단가.

    A 와 C 는 km당 단가가 같으므로 운송비 비율이 거리 비율과 같아야 한다.
    """
    by_name = {c.name: c for c in _recommend(session).candidates}
    a, c = by_name["A 청과도매"], by_name["C 도매시장"]

    assert a.transport_cost_krw == pytest.approx(a.distance_km * 3000, abs=1)
    assert c.transport_cost_krw == pytest.approx(c.distance_km * 3000, abs=1)
    assert c.transport_cost_krw / a.transport_cost_krw == pytest.approx(
        c.distance_km / a.distance_km
    )
    # 가까운 B 는 같은 1,000kg 을 팔면서 운송비가 A 의 절반 이하다.
    assert by_name["B 농산물유통"].transport_cost_krw < a.transport_cost_krw


def test_reason_is_korean_and_explains_the_rank(session: Session) -> None:
    top = _recommend(session).candidates[0]
    assert top.reason.startswith("1위 · 예상 순수익 242만 2,600원")
    assert "운송비 8만원(40.0km)" in top.reason
    assert "수수료 3%" in top.reason


def test_format_krw_matches_spec_notation() -> None:
    assert service._format_krw(2_422_600) == "242만 2,600원"
    assert service._format_krw(80_000) == "8만원"
    assert service._format_krw(3_500) == "3,500원"
    assert service._format_krw(-12_000) == "-1만 2,000원"


# --------------------------------------------------------------------------
# 피드백 루프 (SPEC 7.1)
# --------------------------------------------------------------------------


def test_seeded_reliability_is_neutral(session: Session) -> None:
    """시드에는 이행 실패가 없으므로 순위 조정이 일어나지 않는다."""
    for c in _recommend(session).candidates:
        assert c.reliability.score == pytest.approx(1.0)
        assert c.ranking_score_krw == pytest.approx(c.net_profit_krw)


def test_pending_proposals_do_not_count_as_failures(session: Session) -> None:
    """아직 선택되지 않은 proposed 거래는 이행률 분모에 들어가지 않는다."""
    hub = session.scalar(select(Wholesaler).where(Wholesaler.name == "B 농산물유통"))
    stats = service.reliability_scores(session)[hub.id]

    assert stats.proposed_total == 2      # settled 1 + proposed 1
    assert stats.decided == 1
    assert stats.fulfilled == 1
    assert stats.score == pytest.approx(1.0)


def test_rejected_history_demotes_a_wholesaler(scratch_session: Session) -> None:
    """이행하지 않은 이력이 쌓이면 순수익 1위라도 밀려난다 (SPEC 7.1)."""
    session = scratch_session
    farm, crop = _tomato_farm(session)
    hub = session.scalar(select(Wholesaler).where(Wholesaler.name == "B 농산물유통"))

    before = service.recommend_wholesalers(
        session,
        farm_id=farm.id,
        crop_id=crop.id,
        qty_kg=OFFERED_KG,
        ship_date=ANCHOR_DATE,
    )
    assert before.candidates[0].name == "B 농산물유통"

    # B 가 제안을 받고도 거래를 성사시키지 못한 이력 8건.
    shipment = session.scalar(select(Shipment).where(Shipment.qty_kg == 800))
    for _ in range(8):
        session.add(
            Deal(
                shipment_id=shipment.id,
                wholesaler_id=hub.id,
                agreed_price_krw=1,
                status=DealStatus.REJECTED,
                decided_on=ANCHOR_DATE,
            )
        )
    session.commit()

    after = service.recommend_wholesalers(
        session,
        farm_id=farm.id,
        crop_id=crop.id,
        qty_kg=OFFERED_KG,
        ship_date=ANCHOR_DATE,
    )
    demoted = {c.name: c for c in after.candidates}["B 농산물유통"]

    assert after.candidates[0].name == "A 청과도매"
    assert demoted.rank == 2
    # 순수익 자체는 그대로다 — 바뀌는 것은 정렬 기준값이다.
    assert demoted.net_profit_krw == pytest.approx(2_422_600, abs=1)
    assert demoted.ranking_score_krw < demoted.net_profit_krw
    assert demoted.reliability.score < service.RELIABILITY_WARN_BELOW
    assert "이행률" in demoted.reason


def test_record_deal_closes_the_other_proposals(scratch_session: Session) -> None:
    """한 곳을 수락하면 같은 출하의 나머지 제안은 rejected 로 닫힌다."""
    session = scratch_session
    shipment = session.scalar(
        select(Shipment).where(Shipment.qty_kg == OFFERED_KG, Shipment.ship_date == ANCHOR_DATE)
    )
    wholesalers = {w.name: w for w in session.scalars(select(Wholesaler))}

    # 추천 3건을 proposed 로 기록한다.
    for name in ("A 청과도매", "C 도매시장"):
        service.record_deal(
            session,
            shipment_id=shipment.id,
            wholesaler_id=wholesalers[name].id,
            status=DealStatus.PROPOSED,
        )
    # 농가가 B 를 선택.
    chosen = service.record_deal(
        session,
        shipment_id=shipment.id,
        wholesaler_id=wholesalers["B 농산물유통"].id,
        status=DealStatus.ACCEPTED,
    )

    assert chosen.status == DealStatus.ACCEPTED
    assert chosen.decided_on == shipment.ship_date
    # 시드가 만들어 둔 B 의 proposed 행이 갱신되었을 뿐, 새 행이 생기지 않았다.
    deals = service.list_deals(session, shipment_id=shipment.id)
    assert len(deals) == 3
    others = [d for d in deals if d.wholesaler_id != chosen.wholesaler_id]
    assert all(d.status == DealStatus.REJECTED for d in others)
    assert all(d.decided_on == shipment.ship_date for d in others)


def test_record_deal_defaults_the_agreed_price(scratch_session: Session) -> None:
    """금액을 안 주면 단가 × min(출하량, 구매 가능량) 으로 채운다."""
    session = scratch_session
    shipment = session.scalar(
        select(Shipment).where(Shipment.qty_kg == OFFERED_KG, Shipment.ship_date == ANCHOR_DATE)
    )
    c = session.scalar(select(Wholesaler).where(Wholesaler.name == "C 도매시장"))

    deal = service.record_deal(
        session,
        shipment_id=shipment.id,
        wholesaler_id=c.id,
        status=DealStatus.SETTLED,
    )
    assert deal.agreed_price_krw == 2700 * 800


def test_record_deal_rejects_unknown_references(scratch_session: Session) -> None:
    with pytest.raises(service.RecommendationError):
        service.record_deal(scratch_session, shipment_id=99_999, wholesaler_id=1)


# --------------------------------------------------------------------------
# 예측 단가 연동 (SPEC 5.1)
# --------------------------------------------------------------------------


def test_use_forecast_falls_back_when_the_service_is_absent(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "load_price_forecaster", lambda: None)
    result = _recommend(session, use_forecast=True)

    assert result.price_source == service.PRICE_SOURCE_STATIC
    assert any("고시 단가" in note for note in result.notes)
    assert {c.unit_price_krw for c in result.candidates} == {2550, 2580, 2700}


def test_use_forecast_replaces_the_unit_price(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """예측 시세가 있으면 그 값이 모든 후보의 단가가 된다."""
    seen: dict = {}

    def fake(session_, *, crop_id, region_id, target_date):
        seen.update(crop_id=crop_id, region_id=region_id, target_date=target_date)
        return 2610.4

    monkeypatch.setattr(service, "load_price_forecaster", lambda: fake)
    result = _recommend(session, use_forecast=True)

    assert result.price_source == service.PRICE_SOURCE_FORECAST
    assert seen["target_date"] == ANCHOR_DATE
    assert {c.unit_price_krw for c in result.candidates} == {2610}
    # 고시 단가는 비교용으로 남는다.
    assert {c.list_unit_price_krw for c in result.candidates} == {2550, 2580, 2700}
    # 단가가 같아지면 거리·수수료·구매 가능량만 남아 가까운 B 가 이긴다.
    assert result.candidates[0].name == "B 농산물유통"


def test_forecast_failure_does_not_break_the_recommendation(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("model not trained")

    monkeypatch.setattr(service, "load_price_forecaster", lambda: boom)
    result = _recommend(session, use_forecast=True)

    assert result.price_source == service.PRICE_SOURCE_STATIC
    assert result.candidates[0].name == "B 농산물유통"


# --------------------------------------------------------------------------
# HTTP 계층
# --------------------------------------------------------------------------


def _payload(client: TestClient, **overrides) -> dict:
    crops = {c["name"]: c["id"] for c in client.get("/api/crops").json()}
    body = {
        "farm_id": 1,
        "crop_id": crops["토마토"],
        "qty_kg": OFFERED_KG,
        "ship_date": ANCHOR_DATE.isoformat(),
    }
    body.update(overrides)
    return body


def test_recommendations_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations/wholesalers", json=_payload(client)
    )
    assert response.status_code == 200
    body = response.json()

    assert body["crop_name"] == "토마토"
    assert body["price_source"] == "static"
    assert [c["name"] for c in body["candidates"]] == [
        "B 농산물유통",
        "A 청과도매",
        "C 도매시장",
    ]
    top = body["candidates"][0]
    assert top["net_profit_krw"] == 2_422_600
    assert top["rank"] == 1
    assert top["reason"]
    # 잔여 물량 경고가 3위 후보에 붙는다.
    assert body["candidates"][2]["unsold_kg"] == 200


def test_recommendations_endpoint_limit(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations/wholesalers", json=_payload(client, limit=1)
    )
    assert len(response.json()["candidates"]) == 1


def test_recommendations_endpoint_validates_quantity(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations/wholesalers", json=_payload(client, qty_kg=0)
    )
    assert response.status_code == 422


def test_recommendations_endpoint_unknown_farm(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations/wholesalers", json=_payload(client, farm_id=99_999)
    )
    assert response.status_code == 404


def test_deals_endpoints(seeded_session_factory: sessionmaker, tmp_path) -> None:
    """POST /api/deals 가 선택을 기록하고 GET 이 그것을 돌려준다."""
    from app.db import build_engine, create_all, get_session
    from app.main import app
    from app.seed import seed_all

    engine = build_engine(str(tmp_path / "http-deals.db"))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        seed_all(s)

    def override():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        with factory() as s:
            shipment = s.scalar(
                select(Shipment).where(
                    Shipment.qty_kg == OFFERED_KG, Shipment.ship_date == ANCHOR_DATE
                )
            )
            hub = s.scalar(select(Wholesaler).where(Wholesaler.name == "B 농산물유통"))

        created = client.post(
            "/api/deals",
            json={
                "shipment_id": shipment.id,
                "wholesaler_id": hub.id,
                "status": "settled",
            },
        )
        assert created.status_code == 201
        assert created.json()["agreed_price_krw"] == 2580 * 1000
        assert created.json()["decided_on"] == ANCHOR_DATE.isoformat()

        listed = client.get("/api/deals", params={"shipment_id": shipment.id}).json()
        assert [d["status"] for d in listed] == ["settled"]

        missing = client.post(
            "/api/deals", json={"shipment_id": 99_999, "wholesaler_id": hub.id}
        )
        assert missing.status_code == 404
    app.dependency_overrides.clear()


def test_farm_origin_is_the_region_centroid(session: Session) -> None:
    """농가 좌표가 없으므로 소속 시군구 좌표를 출발점으로 쓴다."""
    farm, _ = _tomato_farm(session)
    region = session.get(Region, farm.region_id)
    assert service.farm_origin(session, farm) == (region.lat, region.lon)
