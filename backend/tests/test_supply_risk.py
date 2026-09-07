"""지역별 수급 위험 조기 알림 (SPEC 5.4).

핵심 회귀는 SPEC 5.4 워크드 예제다: 양파 120톤 출하 + 8톤 재고 = 128톤 공급,
수요 100톤, 초과 28톤, 위험 단계 "위험", 그리고 정확히 28톤을 채우는 대응 방안.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Crop, Region
from app.seed import (
    ANCHOR_DATE,
    ONION_DEMAND_KG,
    ONION_INVENTORY_KG,
    ONION_SHIPMENTS_KG,
)
from app.services import supply_risk as service

ONION_EXCESS_KG = ONION_SHIPMENTS_KG + ONION_INVENTORY_KG - ONION_DEMAND_KG

HOME_REGION = "충남 논산시"


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


def _region(session: Session, name: str = HOME_REGION) -> Region:
    return session.scalars(select(Region).where(Region.name == name)).one()


def _crop(session: Session, name: str) -> Crop:
    return session.scalars(select(Crop).where(Crop.name == name)).one()


def _onion_window() -> service.AnalysisWindow:
    """시드의 양파 수요 기간과 같은 창."""
    return service.resolve_window(ANCHOR_DATE, ANCHOR_DATE + timedelta(days=21))


# --------------------------------------------------------------------------
# SPEC 5.4 워크드 예제
# --------------------------------------------------------------------------


def test_onion_volume_breakdown_matches_spec(session: Session) -> None:
    assessment = service.assess_region_crop(
        session, _region(session), _crop(session, "양파"), _onion_window()
    )
    volumes = assessment.volumes

    assert volumes.farm_shipment_kg == 120_000        # 농가 출하 예정량 120톤
    assert volumes.wholesaler_inventory_kg == 8_000   # 도매처 기존 재고량 8톤
    assert volumes.total_supply_kg == 128_000         # 전체 공급량 128톤
    assert volumes.buyer_demand_kg == 100_000         # 판매처 구매 수요량 100톤
    assert volumes.excess_supply_kg == 28_000         # 예상 초과 공급량 28톤
    assert volumes.excess_supply_kg == ONION_EXCESS_KG


def test_onion_risk_tier_is_danger(session: Session) -> None:
    assessment = service.assess_region_crop(
        session, _region(session), _crop(session, "양파"), _onion_window()
    )
    assert assessment.excess_ratio == pytest.approx(28_000 / 128_000)
    assert assessment.excess_ratio >= service.RISK_DANGER_RATIO
    assert assessment.risk_tier is service.RiskTier.DANGER
    assert assessment.risk_tier.value == "위험"


def test_onion_mitigation_plan_sums_to_the_excess(session: Session) -> None:
    plan = service.assess_region_crop(
        session, _region(session), _crop(session, "양파"), _onion_window()
    ).mitigation

    # SPEC 5.4 의 네 가지 대응 방안이 표 순서대로 모두 나온다.
    assert [a.label for a in plan.actions] == [
        "식품가공업체 추가 연결",
        "학교급식 업체 추가 연결",
        "출하 시기 조정",
        "지역 공동판매 연계",
    ]
    # 합계 = 초과 물량, 부족분 없음.
    assert sum(a.qty_kg for a in plan.actions) == 28_000
    assert plan.planned_kg == 28_000
    assert plan.shortfall_kg == 0
    assert plan.is_fully_covered
    # 어떤 채널도 자기 여력을 넘겨 배정받지 않는다.
    for action in plan.actions:
        assert 0 <= action.qty_kg <= action.capacity_kg
        assert action.headroom_kg == action.capacity_kg - action.qty_kg


def test_mitigation_respects_channel_capacity_order(session: Session) -> None:
    """우선순위대로 채워지므로 앞 채널은 여력을 다 쓴 뒤에야 다음으로 넘어간다."""
    plan = service.assess_region_crop(
        session, _region(session), _crop(session, "양파"), _onion_window()
    ).mitigation
    by_channel = {a.channel: a for a in plan.actions}

    # 가공(15톤 등록 수요 × 0.80)과 급식(25톤 × 0.30)은 여력을 전부 소진한다.
    assert by_channel[service.MitigationChannel.PROCESSOR].qty_kg == 12_000
    assert by_channel[service.MitigationChannel.SCHOOL_MEAL].qty_kg == 7_500
    # 출하 연기는 창 내 출하량의 5% 가 상한이다.
    assert by_channel[service.MitigationChannel.SHIPPING_SHIFT].qty_kg == 6_000
    # 남은 물량만 지역 공동판매로 간다 — 여력은 아직 남아 있다.
    local = by_channel[service.MitigationChannel.LOCAL_JOINT]
    assert local.qty_kg == 2_500
    assert local.headroom_kg > 0


# --------------------------------------------------------------------------
# 여력 부족 경로
# --------------------------------------------------------------------------


def test_capacity_shortfall_is_reported_not_fudged(session: Session) -> None:
    """수요·출하가 모두 창 밖인 기간 — 재고 8톤만 남고 흡수할 창구가 없다."""
    start = ANCHOR_DATE + timedelta(days=22)  # 양파 수요는 +21 일에 끝난다
    window = service.resolve_window(start, start + timedelta(days=7))

    assessment = service.assess_region_crop(
        session, _region(session), _crop(session, "양파"), window
    )
    volumes = assessment.volumes

    assert volumes.farm_shipment_kg == 0
    assert volumes.wholesaler_inventory_kg == ONION_INVENTORY_KG
    assert volumes.buyer_demand_kg == 0
    assert volumes.excess_supply_kg == ONION_INVENTORY_KG
    assert assessment.risk_tier is service.RiskTier.DANGER

    plan = assessment.mitigation
    by_channel = {a.channel: a for a in plan.actions}
    # 등록 수요가 없으므로 각 채널의 여력은 판매처의 표준 구매량에서만 나온다
    # ("추가 연결" — 아직 이 품목을 사지 않는 곳을 새로 붙이는 경우).
    assert by_channel[service.MitigationChannel.PROCESSOR].capacity_kg == 400
    assert by_channel[service.MitigationChannel.SCHOOL_MEAL].capacity_kg == 210
    assert by_channel[service.MitigationChannel.LOCAL_JOINT].capacity_kg == 180
    # 창 안에 출하가 없으니 미룰 물량도 없다.
    assert by_channel[service.MitigationChannel.SHIPPING_SHIFT].capacity_kg == 0

    # 있는 여력은 남김없이 쓰지만 8톤에는 한참 못 미친다.
    assert all(a.qty_kg == a.capacity_kg for a in plan.actions)
    assert plan.planned_kg == 790
    assert plan.shortfall_kg == ONION_INVENTORY_KG - 790
    assert not plan.is_fully_covered
    # 배분 합계 + 부족분은 언제나 처리 대상 물량과 같다.
    assert plan.planned_kg + plan.shortfall_kg == plan.target_kg
    assert plan.target_kg == volumes.excess_supply_kg


def test_partial_capacity_still_reports_the_gap(session: Session) -> None:
    """여력이 일부만 있을 때도 있는 만큼만 배정하고 나머지를 부족분으로 남긴다."""
    plan = service.plan_mitigation(
        session,
        _region(session),
        _crop(session, "양파"),
        _onion_window(),
        excess_supply_kg=999_999,
        buyers=service.catchment_buyers(session, _region(session)),
        registered=service.registered_demand_by_buyer(
            session,
            _crop(session, "양파"),
            [b.id for b in service.catchment_buyers(session, _region(session))],
            _onion_window(),
        ),
        window_shipment_kg=ONION_SHIPMENTS_KG,
    )
    # 모든 채널이 여력 상한까지 찼는데도 초과 물량을 다 덮지 못한다.
    assert all(a.qty_kg == a.capacity_kg for a in plan.actions)
    assert plan.planned_kg == sum(a.capacity_kg for a in plan.actions)
    assert plan.shortfall_kg == 999_999 - plan.planned_kg
    assert plan.shortfall_kg > 0
    assert not plan.is_fully_covered


def test_supply_shortage_is_stable(session: Session) -> None:
    """수요가 공급보다 많으면 초과 공급은 음수이고 위험 단계는 안정이다.

    창 시작(+8일) 전에 유통기한이 끝나는 규격외 500kg·임박 200kg 재고는 이 창의
    공급이 아니므로, 토마토 재고 1,700kg 중 1,000kg 만 남는다. 수요는 1,700kg.
    """
    start = ANCHOR_DATE + timedelta(days=8)
    window = service.resolve_window(start, start + timedelta(days=6))
    assessment = service.assess_region_crop(
        session, _region(session), _crop(session, "토마토"), window
    )
    assert assessment.volumes.farm_shipment_kg == 0
    assert assessment.volumes.wholesaler_inventory_kg == 1_000
    assert assessment.volumes.buyer_demand_kg == 1_700
    assert assessment.volumes.excess_supply_kg == -700
    assert assessment.excess_ratio == pytest.approx(-0.7)
    assert assessment.risk_tier is service.RiskTier.STABLE
    assert assessment.mitigation.target_kg == 0
    assert assessment.mitigation.planned_kg == 0
    assert assessment.mitigation.shortfall_kg == 0
    assert all(a.qty_kg == 0 for a in assessment.mitigation.actions)


# --------------------------------------------------------------------------
# 임계값 · 창 해석
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (-0.10, service.RiskTier.STABLE),
        (0.0, service.RiskTier.STABLE),
        (service.RISK_WATCH_RATIO - 0.001, service.RiskTier.STABLE),
        (service.RISK_WATCH_RATIO, service.RiskTier.WATCH),
        (service.RISK_DANGER_RATIO - 0.001, service.RiskTier.WATCH),
        (service.RISK_DANGER_RATIO, service.RiskTier.DANGER),
        (1.0, service.RiskTier.DANGER),
    ],
)
def test_risk_tier_thresholds(ratio: float, expected: service.RiskTier) -> None:
    assert service.risk_tier(ratio) is expected


def test_window_defaults_to_anchor_date() -> None:
    window = service.resolve_window()
    assert window.start == ANCHOR_DATE
    assert window.end == ANCHOR_DATE + timedelta(days=service.DEFAULT_WINDOW_DAYS)


def test_reversed_window_is_rejected() -> None:
    with pytest.raises(service.InvalidWindowError):
        service.resolve_window(ANCHOR_DATE, ANCHOR_DATE - timedelta(days=1))


def test_catchment_covers_neighbouring_market_towns(session: Session) -> None:
    """수급권은 시군구 경계가 아니라 반경으로 잡는다 — 재고 도매처는 부여에 있다."""
    region = _region(session)
    wholesaler_regions = {
        w.region_id for w in service.catchment_wholesalers(session, region)
    }
    buyer_regions = {b.region_id for b in service.catchment_buyers(session, region)}
    assert wholesaler_regions - {region.id}
    assert buyer_regions - {region.id}


# --------------------------------------------------------------------------
# HTTP 계층
# --------------------------------------------------------------------------


def test_supply_risk_endpoint(client: TestClient, session: Session) -> None:
    response = client.get(
        "/api/supply-risk",
        params={
            "region_id": _region(session).id,
            "crop_id": _crop(session, "양파").id,
            "window_start": ANCHOR_DATE.isoformat(),
            "window_end": (ANCHOR_DATE + timedelta(days=21)).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["crop"]["name"] == "양파"
    assert body["region"]["name"] == HOME_REGION
    assert body["volumes"] == {
        "farm_shipment_kg": 120_000,
        "wholesaler_inventory_kg": 8_000,
        "total_supply_kg": 128_000,
        "buyer_demand_kg": 100_000,
        "excess_supply_kg": 28_000,
    }
    assert body["risk_tier"] == "위험"
    assert body["mitigation"]["planned_kg"] == 28_000
    assert body["mitigation"]["shortfall_kg"] == 0
    assert sum(a["qty_kg"] for a in body["mitigation"]["actions"]) == 28_000


def test_supply_risk_endpoint_defaults_the_window(
    client: TestClient, session: Session
) -> None:
    response = client.get(
        "/api/supply-risk",
        params={"region_id": _region(session).id, "crop_id": _crop(session, "양파").id},
    )
    assert response.status_code == 200
    assert response.json()["window"] == {
        "start": ANCHOR_DATE.isoformat(),
        "end": (ANCHOR_DATE + timedelta(days=service.DEFAULT_WINDOW_DAYS)).isoformat(),
    }


def test_supply_risk_endpoint_unknown_ids_are_404(
    client: TestClient, session: Session
) -> None:
    crop_id = _crop(session, "양파").id
    assert (
        client.get(
            "/api/supply-risk", params={"region_id": 9999, "crop_id": crop_id}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/supply-risk",
            params={"region_id": _region(session).id, "crop_id": 9999},
        ).status_code
        == 404
    )


def test_supply_risk_endpoint_rejects_reversed_window(
    client: TestClient, session: Session
) -> None:
    response = client.get(
        "/api/supply-risk",
        params={
            "region_id": _region(session).id,
            "crop_id": _crop(session, "양파").id,
            "window_start": ANCHOR_DATE.isoformat(),
            "window_end": (ANCHOR_DATE - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422


def test_alerts_endpoint_lists_the_onion_risk(
    client: TestClient, session: Session
) -> None:
    response = client.get("/api/alerts", params={"region_id": _region(session).id})
    assert response.status_code == 200
    alerts = response.json()

    assert alerts, "양파가 위험 단계이므로 최소 한 건은 나와야 한다"
    onion = next(a for a in alerts if a["crop"]["name"] == "양파")
    assert onion["risk_tier"] == "위험"
    assert onion["excess_supply_kg"] == 28_000
    assert onion["total_supply_kg"] == 128_000
    assert onion["buyer_demand_kg"] == 100_000
    assert "양파" in onion["headline"] and "위험" in onion["headline"]
    # 안정 단계는 목록에 없고, 위험한 순서로 정렬된다.
    assert all(a["risk_tier"] in {"주의", "위험"} for a in alerts)
    assert [a["excess_ratio"] for a in alerts] == sorted(
        (a["excess_ratio"] for a in alerts), reverse=True
    )


def test_alerts_endpoint_unknown_region_is_404(client: TestClient) -> None:
    assert client.get("/api/alerts", params={"region_id": 9999}).status_code == 404
