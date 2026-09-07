"""Reference-data lookups shared by every feature.

This is also the worked example of the layering convention: routers stay thin,
all querying lives in ``app/services/<feature>.py``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Crop, Region, Wholesaler


def list_regions(session: Session) -> list[Region]:
    return list(session.scalars(select(Region).order_by(Region.name)))


def list_crops(session: Session) -> list[Crop]:
    return list(session.scalars(select(Crop).order_by(Crop.id)))


def list_wholesalers(session: Session) -> list[Wholesaler]:
    """도매처 목록. 추천 결과(SPEC 5.2)와 거래 기록(SPEC 7.1)이 도매처 id 만
    들고 다니므로, 화면이 이름을 붙이려면 이 목록이 필요하다."""
    return list(session.scalars(select(Wholesaler).order_by(Wholesaler.id)))
