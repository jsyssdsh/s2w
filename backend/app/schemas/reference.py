"""Pydantic v2 schemas for the shared reference data."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lat: float
    lon: float


class CropOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    unit: str
