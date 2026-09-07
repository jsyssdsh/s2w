"""Application settings.

Every knob is an environment variable so the same image runs in dev, test and
the demo container. See ``.env.example`` at the repo root.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite file backing the SQLAlchemy engine. The container mounts /app/db.
    db_path: str = "/app/db/farmflow.db"

    # Mosquitto broker used by the smartfarm control loop (SPEC 7.2).
    mqtt_broker_url: str = ""

    # Populate an empty database on startup.
    seed_on_start: bool = True

    # Deterministic canned LLM responses instead of a live provider.
    llm_mock: bool = False

    # Directory holding the exported Next.js frontend, served at "/".
    static_dir: str = "/app/static"


@lru_cache
def get_settings() -> Settings:
    return Settings()
