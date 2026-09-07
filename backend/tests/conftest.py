from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

# Must happen before `app.config` / `app.db` are imported: the module-level
# engine is built from these at import time.
_TMP_DB = Path(tempfile.mkdtemp(prefix="farmflow-test-")) / "app.db"
os.environ["DB_PATH"] = str(_TMP_DB)
os.environ["SEED_ON_START"] = "false"
os.environ["STATIC_DIR"] = str(_TMP_DB.parent / "no-static")


@pytest.fixture(scope="session")
def seeded_session_factory(tmp_path_factory: pytest.TempPathFactory) -> sessionmaker:
    """A throwaway SQLite file seeded once for the whole test session."""
    from app.db import build_engine, create_all
    from app.seed import seed_all

    db_path = tmp_path_factory.mktemp("db") / "seeded.db"
    engine = build_engine(str(db_path))
    create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        seed_all(session)
    return factory


@pytest.fixture
def session(seeded_session_factory: sessionmaker) -> Iterator[Session]:
    with seeded_session_factory() as s:
        yield s
