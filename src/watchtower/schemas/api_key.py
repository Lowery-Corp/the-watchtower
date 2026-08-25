"""Safe contracts for profile-owned API keys."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiKeyCreate(BaseModel):
    """Request one events-write key bound to a machine source service."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    service_id: UUID
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def expiry_must_be_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Expiry must include a timezone")
        normalized = value.astimezone(UTC)
        if normalized <= datetime.now(UTC):
            raise ValueError("Expiry must be in the future")
        return normalized


class ApiKeyUpdate(BaseModel):
    """Mutable key metadata; secret and profile ownership cannot change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_update(self) -> "ApiKeyUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if "expires_at" in self.model_fields_set and self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("Expiry must include a timezone")
            self.expires_at = self.expires_at.astimezone(UTC)
            if self.expires_at <= datetime.now(UTC):
                raise ValueError("Expiry must be in the future")
        return self


class ApiKeyRead(BaseModel):
    """Non-secret API-key metadata safe for repeated retrieval."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    public_prefix: str
    scopes: list[str]
    service_id: UUID | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyRead):
    """Creation-only response containing the one-time plaintext token."""

    api_key: str
