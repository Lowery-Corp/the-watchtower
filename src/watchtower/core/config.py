"""Application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    webhook_secrets: dict[str, SecretStr] = Field(default_factory=dict)
    webhook_signature_tolerance_seconds: int = Field(default=300, ge=1, le=3600)
    max_webhook_body_bytes: int = Field(default=256 * 1024, ge=1024, le=10 * 1024 * 1024)
    webhook_rate_limit_requests: int = Field(default=60, ge=1, le=100_000)
    webhook_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)


@lru_cache
def get_settings() -> Settings:
    """Return the process settings singleton."""

    return Settings()
