"""지역·품목 등 공통 참조 데이터."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.reference import CropOut, RegionOut
from app.services import reference as service

router = APIRouter(prefix="/api", tags=["reference"])


@router.get("/regions", response_model=list[RegionOut])
def list_regions(session: Session = Depends(get_session)) -> list[RegionOut]:
    return [RegionOut.model_validate(r) for r in service.list_regions(session)]


@router.get("/crops", response_model=list[CropOut])
def list_crops(session: Session = Depends(get_session)) -> list[CropOut]:
    return [CropOut.model_validate(c) for c in service.list_crops(session)]
