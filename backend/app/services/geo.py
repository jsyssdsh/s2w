"""Geospatial helpers — the PostGIS stand-in.

SPEC 6.2 calls for PostgreSQL + PostGIS for distance work. This prototype runs
on SQLite, so every distance calculation in the codebase goes through
``haversine_km`` here. When the DB moves to PostGIS, this module is the single
place that changes.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS84 points."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = phi2 - phi1
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def transport_cost_krw(distance_km: float, cost_per_km: int) -> int:
    """운송비 = 거리 × km당 단가, rounded to whole KRW."""
    return round(distance_km * cost_per_km)
