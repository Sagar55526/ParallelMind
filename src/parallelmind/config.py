"""Environment-driven settings.

Why a single settings object?
- Centralized config = one place to override for tests, one place to document.
- pydantic-settings validates types at load time, so a malformed URL fails fast
  at startup rather than surfacing as a confusing runtime error inside a worker.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "parallelmind"
    log_level: str = "INFO"

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = (
        "postgresql+asyncpg://parallelmind:parallelmind@localhost:5432/parallelmind"
    )

    async_worker_count: int = Field(default=10, ge=1, le=10_000)
    queue_name: str = "parallelmind:tasks:default"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor. lru_cache avoids re-reading .env on every call."""
    return Settings()
