"""Liveness endpoint. The docker healthcheck polls this."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
