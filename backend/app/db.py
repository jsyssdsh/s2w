"""Engine, session factory and the FastAPI session dependency.

SQLite stands in for the PostgreSQL + PostGIS of SPEC 6 so the whole system
runs in one container. Everything goes through SQLAlchemy 2.0 — no raw SQL —
so the swap stays a one-line engine change. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


def _database_url(db_path: str) -> str:
    if db_path == ":memory:":
        return "sqlite+pysqlite:///:memory:"
    return f"sqlite+pysqlite:///{db_path}"


def _ensure_parent(db_path: str) -> None:
    if db_path == ":memory:":
        return
    parent = Path(db_path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def build_engine(db_path: str | None = None) -> Engine:
    path = db_path or get_settings().db_path
    _ensure_parent(path)
    engine = create_engine(
        _database_url(path),
        # FastAPI serves requests from a thread pool; sessions are per-request.
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_all(target: Engine | None = None) -> None:
    Base.metadata.create_all(target or engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
