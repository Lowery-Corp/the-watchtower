"""Application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed Watchtower settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WATCHTOWER_",
        extra="ignore",
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    database_url: str = (
        "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower"
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process settings singleton."""

    return Settings()
