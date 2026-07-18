"""Schemas for monitored service identities."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from watchtower.schemas.event import EnvironmentName, SourceSlug


class MonitoredServiceRead(BaseModel):
    """Safe monitored-service representation without signing credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: SourceSlug
    display_name: str
    environment: EnvironmentName
    active: bool
    secret_key_id: str
