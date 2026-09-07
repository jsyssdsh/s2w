"""Reference-data lookups shared by every feature.

This is also the worked example of the layering convention: routers stay thin,
all querying lives in ``app/services/<feature>.py``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Crop, Region


def list_regions(session: Session) -> list[Region]:
    return list(session.scalars(select(Region).order_by(Region.name)))


def list_crops(session: Session) -> list[Crop]:
    return list(session.scalars(select(Crop).order_by(Crop.id)))
