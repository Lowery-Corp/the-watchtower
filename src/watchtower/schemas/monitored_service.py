"""Contracts for profile-owned monitored services."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from watchtower.schemas.event import EnvironmentName, SourceSlug


class MonitoredServiceCreate(BaseModel):
    """Create one event source inside the authenticated profile."""

    model_config = ConfigDict(extra="forbid")

    slug: SourceSlug
    display_name: str = Field(min_length=1, max_length=255)
    environment: EnvironmentName


class MonitoredServiceUpdate(BaseModel):
    """Mutable service metadata; ownership and slug remain stable."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    environment: EnvironmentName | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def require_update(self) -> "MonitoredServiceUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class MonitoredServiceRead(BaseModel):
    """Safe service representation without credential metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: SourceSlug
    display_name: str
    environment: EnvironmentName
    active: bool
    created_at: datetime
    updated_at: datetime
