"""Application configuration."""

from functools import lru_cache
from typing import Literal
from uuid import UUID

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
    auth_service_url: str = "http://100.97.236.10:8000"
    auth_service_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    session_cookie_name: str = Field(default="watchtower_session", min_length=1, max_length=64)
    session_cookie_max_age_seconds: int = Field(default=3600, ge=60, le=86_400)
    session_cookie_secure: bool = True
    session_cookie_same_site: Literal["lax", "strict"] = "lax"
    browser_allowed_origins: set[str] = Field(default_factory=set)
    webhook_secrets: dict[str, SecretStr] = Field(default_factory=dict)
    legacy_webhook_profiles: dict[str, UUID] = Field(default_factory=dict)
    webhook_signature_tolerance_seconds: int = Field(default=300, ge=1, le=3600)
    max_webhook_body_bytes: int = Field(default=256 * 1024, ge=1024, le=10 * 1024 * 1024)
    webhook_rate_limit_requests: int = Field(default=60, ge=1, le=100_000)
    webhook_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)


@lru_cache
def get_settings() -> Settings:
    """Return the process settings singleton."""

    return Settings()
