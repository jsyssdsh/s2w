"""``app/routers/`` 자동 등록 — 기능 bead 가 main.py 를 건드리지 않게 하는 장치.

라우트가 조용히 사라지는 것이 이 구조의 유일한 위험이므로, 전체 라우트 표를
여기에 못 박아 둔다. 라우트를 의도적으로 추가·변경했다면 이 표도 같이 고친다.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI

from app import routers
from app.routers import discover_routers, include_all

# 이 변경 전에 등록돼 있던 라우트 전부. 축소되면 테스트가 깨진다.
EXPECTED_ROUTES = {
    ("/api/alerts", "GET"),
    ("/api/crops", "GET"),
    ("/api/deals", "GET"),
    ("/api/deals", "POST"),
    ("/api/forecast/price", "GET"),
    ("/api/forecast/shipping-window", "POST"),
    ("/api/health", "GET"),
    ("/api/parcels/geojson", "GET"),
    ("/api/parcels/match", "POST"),
    ("/api/parcels/summary", "GET"),
    ("/api/parcels/{parcel_id}", "GET"),
    ("/api/parcels/{parcel_id}/applications", "POST"),
    ("/api/recommendations/buyers", "POST"),
    ("/api/recommendations/wholesalers", "POST"),
    ("/api/regions", "GET"),
    ("/api/smartfarm/{smartfarm_id}/controls", "GET"),
    ("/api/smartfarm/{smartfarm_id}/controls", "POST"),
    ("/api/smartfarm/{smartfarm_id}/readings", "GET"),
    ("/api/smartfarm/{smartfarm_id}/readings", "POST"),
    ("/api/smartfarm/{smartfarm_id}/status", "GET"),
    ("/api/smartfarms", "GET"),
    ("/api/supply-risk", "GET"),
    ("/api/wholesalers/{wholesaler_id}/inventory", "GET"),
}

ROUTERS_DIR = Path(routers.__path__[0])


def _route_table(app: FastAPI) -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return {(path, method.upper()) for path, ops in paths.items() for method in ops}


@pytest.fixture
def temp_router_module() -> Iterator:
    """``app/routers/`` 에 임시 모듈을 떨어뜨렸다가 반드시 치운다."""
    written: list[Path] = []

    def write(name: str, source: str) -> None:
        path = ROUTERS_DIR / f"{name}.py"
        assert not path.exists(), f"{path} 가 이미 있다 — 테스트 이름을 바꿔라"
        path.write_text(source, encoding="utf-8")
        written.append(path)
        importlib.invalidate_caches()

    try:
        yield write
    finally:
        for path in written:
            path.unlink(missing_ok=True)
            sys.modules.pop(f"app.routers.{path.stem}", None)
        importlib.invalidate_caches()


def test_app_registers_every_expected_route() -> None:
    """main.py 를 손대지 않고도 기존 라우트가 전부 살아 있다."""
    from app.main import app

    assert _route_table(app) >= EXPECTED_ROUTES


def test_health_path_is_untouched() -> None:
    """도커 healthcheck 가 의존하므로 별도로 못 박는다 (ARCHITECTURE 3절)."""
    from app.main import app

    assert ("/api/health", "GET") in _route_table(app)


def test_discovery_order_is_sorted_by_module_name() -> None:
    """경로 해석 순서를 재현 가능하게 유지한다."""
    names = [name for name, _ in discover_routers()]
    assert names == sorted(names)
    assert {
        "buyer_match",
        "health",
        "parcel_match",
        "price_forecast",
        "reference",
        "smartfarm",
        "supply_risk",
        "wholesaler_rec",
    } <= set(names)


def test_new_router_file_is_picked_up_without_editing_main(temp_router_module) -> None:
    """기능 추가 = app/routers/ 에 파일 하나. main.py 편집은 필요 없다."""
    temp_router_module(
        "zz_discovery_probe",
        "from fastapi import APIRouter\n"
        'router = APIRouter(prefix="/api", tags=["probe"])\n'
        '@router.get("/zz-discovery-probe")\n'
        "def probe() -> dict[str, bool]:\n"
        "    return {'ok': True}\n",
    )

    app = FastAPI()
    include_all(app)

    assert ("/api/zz-discovery-probe", "GET") in _route_table(app)
    # 새 파일이 기존 라우트를 밀어내지도 않는다.
    assert _route_table(app) >= EXPECTED_ROUTES


def test_module_without_router_is_skipped(temp_router_module) -> None:
    temp_router_module(
        "zz_no_router_probe",
        "WEIGHTS = {'water': 0.3}\n",
    )

    names = [name for name, _ in discover_routers()]
    assert "zz_no_router_probe" not in names

    app = FastAPI()
    include_all(app)
    assert _route_table(app) >= EXPECTED_ROUTES


def test_broken_router_module_fails_loudly(temp_router_module) -> None:
    """라우트가 조용히 사라지는 것보다 부팅 실패가 낫다."""
    temp_router_module(
        "zz_broken_probe",
        "raise RuntimeError('boom')\n",
    )

    with pytest.raises(RuntimeError, match="boom"):
        discover_routers()
