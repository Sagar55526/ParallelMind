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
        "postgresql+asyncpg://parallelmind:parallelmind@localhost:5434/parallelmind"
    )

    async_worker_count: int = Field(default=10, ge=1, le=10_000)
    queue_name: str = "parallelmind:tasks:default"


def get_settings() -> Settings:
    return Settings()
