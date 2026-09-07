"""FastAPI application entry point.

Keep this file boring: one ``include_router`` line per feature and nothing
else feature-specific, so parallel feature branches do not collide here.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import SessionLocal, create_all
from app.routers import (
    buyer_match,
    farm,
    health,
    parcel_match,
    price_forecast,
    reference,
    smartfarm,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    create_all()
    if settings.seed_on_start:
        from app.seed import seed_if_empty

        with SessionLocal() as session:
            inserted = seed_if_empty(session)
        logger.info("seed_on_start: %s", "seeded" if inserted else "already populated")
    yield


app = FastAPI(
    title="울퉁불퉁 농장 AI (FarmFlow AI)",
    description="휴경농지·스마트팜·농산물 유통 데이터를 하나로 묶은 통합 플랫폼 API",
    version="0.1.0",
    lifespan=lifespan,
)

# --- feature routers (one line each) --------------------------------------
app.include_router(health.router)
app.include_router(reference.router)
app.include_router(buyer_match.router)
app.include_router(farm.router)
app.include_router(parcel_match.router)
app.include_router(price_forecast.router)
app.include_router(smartfarm.router)
# --------------------------------------------------------------------------


def _mount_frontend(application: FastAPI) -> None:
    """Serve the exported Next.js site at "/" when it is present.

    Absent in local backend-only development; the container always has it.
    """
    static_dir = Path(get_settings().static_dir)
    if not static_dir.is_dir():
        logger.info("static dir %s missing — serving API only", static_dir)
        return

    application.mount(
        "/_next",
        StaticFiles(directory=static_dir / "_next", check_dir=False),
        name="next-assets",
    )

    @application.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # Unmatched API paths are a 404, not the landing page.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        # `output: 'export'` writes <route>/index.html and <route>.html.
        for candidate in (
            static_dir / full_path,
            static_dir / f"{full_path}.html",
            static_dir / full_path / "index.html",
        ):
            if full_path and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")


_mount_frontend(app)
