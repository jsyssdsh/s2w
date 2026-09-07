from __future__ import annotations

import pytest

from app.services.geo import haversine_km, transport_cost_krw


def test_haversine_zero_distance() -> None:
    assert haversine_km(36.1872, 127.0988, 36.1872, 127.0988) == 0.0


def test_haversine_known_distance() -> None:
    # 논산시청 → 서울시청, roughly 155 km.
    km = haversine_km(36.187153, 127.098769, 37.566535, 126.977969)
    assert km == pytest.approx(154.0, abs=3.0)


def test_haversine_is_symmetric() -> None:
    a = haversine_km(36.1, 127.1, 35.9, 126.9)
    b = haversine_km(35.9, 126.9, 36.1, 127.1)
    assert a == pytest.approx(b)


def test_transport_cost_rounds_to_whole_krw() -> None:
    assert transport_cost_krw(60.0, 3000) == 180_000
    assert isinstance(transport_cost_krw(17.4, 2000), int)
