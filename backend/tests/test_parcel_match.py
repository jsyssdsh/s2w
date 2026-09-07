"""SPEC 5.6 / 7.3 / 4.4 / 4.5 — 유휴농지 적합도 매칭과 지도 데이터."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Crop, Parcel, ParcelStatus, Region
from app.seed import ANCHOR_DATE
from app.services import parcel_match as service

# SPEC 5.6 활용 예시: 딸기 재배를 준비하는 신규 농업인이 700~1,000평 농지를 찾는다.
STRAWBERRY_QUERY = {
    "area_min_pyeong": 700,
    "area_max_pyeong": 1000,
    # C 농지(70만 원)까지 예산 안에 들어오게 잡아, 순위가 임대료 컷오프가 아니라
    # 적합도 점수에서 갈리는지 본다.
    "budget_krw_per_month": 700_000,
}


@pytest.fixture
def fresh_session(tmp_path) -> Iterator[Session]:
    """신청으로 상태를 바꾸는 테스트를 위한, 세션 공유가 없는 DB."""
    from app.db import build_engine, create_all
    from app.seed import seed_all

    engine = build_engine(str(tmp_path / "fresh.db"))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        seed_all(s)
    with factory() as s:
        yield s


@pytest.fixture
def client(seeded_session_factory: sessionmaker) -> Iterator[TestClient]:
    from app.db import get_session
    from app.main import app

    def override() -> Session:
        with seeded_session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _crop_id(session: Session, name: str) -> int:
    return session.scalars(select(Crop).where(Crop.name == name)).one().id


def _match(session: Session, **overrides):
    query = {**STRAWBERRY_QUERY, "crop_id": _crop_id(session, "딸기"), **overrides}
    return service.match_parcels(session, **query)


# --------------------------------------------------------------------------
# 가중치 블록
# --------------------------------------------------------------------------


def test_weights_sum_to_one() -> None:
    assert sum(service.WEIGHTS.values()) == pytest.approx(1.0)
    assert set(service.WEIGHTS) == set(service.AXIS_LABELS)


def test_water_is_the_heaviest_axis() -> None:
    """농업용수는 SPEC 표에서 C 를 3위로 밀어내는 축이므로 가장 무겁다."""
    assert service.WEIGHT_WATER == max(service.WEIGHTS.values())


# --------------------------------------------------------------------------
# SPEC 5.6 워크드 예제
# --------------------------------------------------------------------------


def test_spec_5_6_ranking_is_a_then_b_then_c(session: Session) -> None:
    matches = _match(session)

    assert [m.parcel.name for m in matches] == ["A 농지", "B 농지", "C 농지"]
    assert [m.rank for m in matches] == [1, 2, 3]
    assert matches[0].total_score > matches[1].total_score > matches[2].total_score


def test_spec_5_6_distances_match_the_comparison_table(session: Session) -> None:
    """도매처 거리 24 / 38 / 17km 는 좌표에서 haversine 으로 나온다."""
    by_name = {m.parcel.name: m for m in _match(session)}

    assert by_name["A 농지"].distance_km == pytest.approx(24.0, abs=0.1)
    assert by_name["B 농지"].distance_km == pytest.approx(38.0, abs=0.1)
    assert by_name["C 농지"].distance_km == pytest.approx(17.0, abs=0.1)


def test_removing_water_from_a_drops_it_below_b(session: Session) -> None:
    """농업용수 미확보는 mild 페널티가 아니라 순위를 뒤집는 하드 페널티다."""
    before = {m.parcel.name: m.total_score for m in _match(session)}

    parcel_a = session.scalars(select(Parcel).where(Parcel.name == "A 농지")).one()
    parcel_a.water_access = False
    session.flush()
    try:
        after = _match(session)
        by_name = {m.parcel.name: m for m in after}
        assert by_name["A 농지"].total_score < by_name["B 농지"].total_score
        assert by_name["A 농지"].total_score < before["A 농지"]
        assert [m.parcel.name for m in after][0] == "B 농지"
    finally:
        session.rollback()


def test_c_loses_despite_the_shortest_wholesaler_distance(session: Session) -> None:
    by_name = {m.parcel.name: m for m in _match(session)}
    axes = {a.axis: a for a in by_name["C 농지"].axes}

    # 거리 축만 보면 C 가 최고점이다 — 그래도 3위여야 한다.
    assert axes["distance"].score > {
        a.axis: a for a in by_name["A 농지"].axes
    }["distance"].score
    assert axes["water"].score == 0.0
    assert by_name["C 농지"].rank == 3


def test_axes_explain_the_total(session: Session) -> None:
    """SPEC 4.4 조건 비교 화면이 근거를 그릴 수 있어야 한다."""
    match = _match(session)[0]

    assert {a.axis for a in match.axes} == set(service.WEIGHTS)
    assert sum(a.weighted for a in match.axes) == pytest.approx(match.total_score)
    for axis in match.axes:
        assert 0.0 <= axis.score <= 1.0
        assert axis.weight == service.WEIGHTS[axis.axis]
    assert "농업용수 확보" in match.reason


def test_area_outside_the_requested_range_is_penalised(session: Session) -> None:
    narrow = {m.parcel.name: m for m in _match(session, area_min_pyeong=950, area_max_pyeong=1000)}
    area_axis = {a.axis: a for a in narrow["C 농지"].axes}["area"]

    assert area_axis.score < 1.0
    assert {a.axis: a for a in narrow["B 농지"].axes}["area"].score == 1.0


def test_over_budget_rent_scores_zero(session: Session) -> None:
    tight = {m.parcel.name: m for m in _match(session, budget_krw_per_month=600_000)}
    rent_axis = {a.axis: a for a in tight["C 농지"].axes}["rent"]

    assert rent_axis.score == 0.0
    assert "예산 60만 원 초과" in tight["C 농지"].reason


def test_region_filter_narrows_candidates(session: Session) -> None:
    nonsan = session.scalars(select(Region).where(Region.name == "충남 논산시")).one()
    matches = _match(session, region_id=nonsan.id)

    assert matches
    assert {m.region.id for m in matches} == {nonsan.id}


# --------------------------------------------------------------------------
# 축별 점수 함수
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("area", "expected"),
    [(700, 1.0), (900, 1.0), (1000, 1.0), (350, 0.5), (2000, 0.0)],
)
def test_area_score(area: int, expected: float) -> None:
    assert service.area_score(area, 700, 1000) == pytest.approx(expected)


def test_rent_score_is_zero_at_or_above_budget() -> None:
    assert service.rent_score(700_000, 700_000) == 0.0
    assert service.rent_score(900_000, 700_000) == 0.0
    assert service.rent_score(350_000, 700_000) == pytest.approx(0.5)


def test_distance_score_reaches_zero_at_the_horizon() -> None:
    assert service.distance_score(0.0) == 1.0
    assert service.distance_score(service.DISTANCE_HORIZON_KM) == 0.0
    assert service.distance_score(service.DISTANCE_HORIZON_KM * 2) == 0.0
    assert service.distance_score(None) == 0.0


def test_soil_grade_ordering() -> None:
    assert service.soil_score("1등급") > service.soil_score("2등급") > service.soil_score("3등급")
    assert service.soil_score("모름") == service.SOIL_GRADE_FALLBACK


# --------------------------------------------------------------------------
# API — 매칭
# --------------------------------------------------------------------------


def test_match_endpoint_returns_ranked_parcels(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/parcels/match",
        json={**STRAWBERRY_QUERY, "crop_id": _crop_id(session, "딸기")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["crop_name"] == "딸기"
    assert body["as_of"] == ANCHOR_DATE.isoformat()
    assert body["weights"] == pytest.approx(service.WEIGHTS)
    assert [r["name"] for r in body["results"]] == ["A 농지", "B 농지", "C 농지"]

    first = body["results"][0]
    assert first["rank"] == 1
    assert first["nearest_wholesaler"]["distance_km"] == pytest.approx(24.0, abs=0.1)
    assert sum(a["weighted"] for a in first["axes"]) == pytest.approx(
        first["total_score"], abs=1e-3
    )
    assert first["reason"]


def test_match_endpoint_honours_limit(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/parcels/match",
        json={**STRAWBERRY_QUERY, "crop_id": _crop_id(session, "딸기"), "limit": 1},
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_match_endpoint_rejects_unknown_crop(client: TestClient) -> None:
    response = client.post("/api/parcels/match", json={**STRAWBERRY_QUERY, "crop_id": 9999})
    assert response.status_code == 404


def test_match_endpoint_rejects_inverted_area_range(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/parcels/match",
        json={
            **STRAWBERRY_QUERY,
            "crop_id": _crop_id(session, "딸기"),
            "area_min_pyeong": 1000,
            "area_max_pyeong": 700,
        },
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# API — SPEC 4.4 지도 / 요약
# --------------------------------------------------------------------------


def test_geojson_is_a_valid_feature_collection(client: TestClient) -> None:
    response = client.get("/api/parcels/geojson")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 3

    for feature in body["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"
        lon, lat = feature["geometry"]["coordinates"]
        assert 124.0 < lon < 132.0 and 33.0 < lat < 39.0
        props = feature["properties"]
        assert props["color"] in {"green", "amber", "red"}
        assert props["condition_label"] in {"상태 최상", "상태 양호", "개선 필요"}
        assert props["status_label"] in {"유휴", "운영 중", "전환 완료"}


def test_geojson_colors_follow_condition(client: TestClient) -> None:
    features = {f["properties"]["name"]: f["properties"] for f in client.get("/api/parcels/geojson").json()["features"]}

    assert features["A 농지"]["color"] == "green"       # 상태 최상
    assert features["B 농지"]["color"] == "amber"       # 상태 양호
    assert features["C 농지"]["color"] == "red"         # 개선 필요


def test_geojson_region_filter(client: TestClient, session: Session) -> None:
    nonsan = session.scalars(select(Region).where(Region.name == "충남 논산시")).one()
    body = client.get("/api/parcels/geojson", params={"region_id": nonsan.id}).json()

    assert body["features"]
    assert {f["properties"]["region_id"] for f in body["features"]} == {nonsan.id}


def test_summary_reports_spec_4_4_headline_metrics(client: TestClient) -> None:
    body = client.get("/api/parcels/summary").json()

    # 시드는 A 운영 중 / B 전환 완료 / C 유휴.
    assert body["operating_count"] == 1
    assert body["converted_count"] == 1
    assert body["idle_count"] == 1
    assert body["total_count"] == 3
    assert body["applications_today"] == 0
    assert body["ai_recommended_deals"] >= 1
    assert 0.0 <= body["land_utilization_rate"] <= 1.0
    assert body["as_of"] == ANCHOR_DATE.isoformat()


# --------------------------------------------------------------------------
# API — SPEC 4.5 상세
# --------------------------------------------------------------------------


def test_parcel_detail_covers_the_spec_4_5_fields(client: TestClient, session: Session) -> None:
    parcel = session.scalars(select(Parcel).where(Parcel.name == "A 농지")).one()
    body = client.get(f"/api/parcels/{parcel.id}").json()

    assert body["area_pyeong"] == 900
    assert body["monthly_rent_krw"] == 650_000
    assert body["soil_grade"] == "1등급"
    assert body["water_access"] is True
    assert body["cold_storage_label"] == "가능"
    assert body["color"] == "green"
    assert 0.0 <= body["land_utilization_rate"] <= 1.0

    # 주변 시설 = 가까운 도매처 3곳 + 냉장창고
    kinds = [f["kind"] for f in body["nearby_facilities"]]
    assert kinds.count("wholesaler") == 3
    assert "cold_storage" in kinds

    # 재배 작물 / 영농 시작일 / 예상 수확량 / 스마트팜 유형
    assert body["smartfarms"]
    smartfarm = body["smartfarms"][0]
    assert smartfarm["crop_name"]
    assert smartfarm["started_on"]
    assert smartfarm["expected_yield_kg"] > 0
    assert smartfarm["type"]


def test_parcel_detail_404(client: TestClient) -> None:
    assert client.get("/api/parcels/9999").status_code == 404


# --------------------------------------------------------------------------
# API — SPEC 7.3 매칭 신청
# --------------------------------------------------------------------------


def test_application_flips_an_idle_parcel_to_operating(fresh_session: Session) -> None:
    from app.db import get_session
    from app.main import app

    def override() -> Session:
        yield fresh_session

    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app) as client:
            parcel = fresh_session.scalars(select(Parcel).where(Parcel.name == "C 농지")).one()
            assert parcel.status is ParcelStatus.IDLE

            payload = {
                "crop_id": _crop_id(fresh_session, "딸기"),
                "applicant_name": "김청년",
                "phone": "010-1000-0001",
                "lease_months": 24,
                "message": "딸기 스마트팜을 조성하고 싶습니다.",
                "match_score": 0.4,
            }
            response = client.post(f"/api/parcels/{parcel.id}/applications", json=payload)

            assert response.status_code == 201
            body = response.json()
            assert body["application"]["status"] == "pending"
            assert body["application"]["applied_on"] == ANCHOR_DATE.isoformat()
            assert body["parcel_status"] == "operating"
            assert body["parcel_status_label"] == "운영 중"

            # SPEC 4.4 "오늘 신청량" 이 올라간다.
            assert client.get("/api/parcels/summary").json()["applications_today"] == 1
            assert client.get(f"/api/parcels/{parcel.id}").json()["application_count"] == 1

            # 같은 필지에 두 번째 신청은 409.
            assert client.post(f"/api/parcels/{parcel.id}/applications", json=payload).status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_application_on_missing_parcel_is_404(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/parcels/9999/applications",
        json={"crop_id": _crop_id(session, "딸기"), "applicant_name": "김청년"},
    )
    assert response.status_code == 404


def test_application_on_unknown_crop_is_409(client: TestClient, session: Session) -> None:
    parcel = session.scalars(select(Parcel).where(Parcel.name == "C 농지")).one()
    response = client.post(
        f"/api/parcels/{parcel.id}/applications",
        json={"crop_id": 9999, "applicant_name": "김청년"},
    )
    assert response.status_code == 409
