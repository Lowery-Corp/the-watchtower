"""Versioned inbound event contracts."""

import re
from datetime import UTC, datetime
from math import isfinite
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

_RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

SourceSlug = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]
EventType = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]
EnvironmentName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]


class EventIngestionAcknowledgement(BaseModel):
    """Stable response for accepted and idempotent duplicate submissions."""

    event_id: UUID
    source_event_id: UUID
    status: Literal["accepted", "duplicate"]
    request_id: str


class EventEnvelope(BaseModel):
    """CloudEvents-inspired version-one event submitted by a source service."""

    model_config = ConfigDict(extra="allow")

    spec_version: Literal["1.0"]
    event_id: UUID
    event_type: EventType
    source: SourceSlug
    subject: str | None = Field(default=None, max_length=255)
    occurred_at: datetime
    severity: Literal["debug", "info", "warning", "error", "critical"] = "info"
    environment: EnvironmentName
    correlation_id: str | None = Field(default=None, max_length=128)
    data: dict[str, Any]

    @field_validator("occurred_at", mode="before")
    @classmethod
    def require_rfc3339_timestamp(cls, value: object) -> object:
        """Reject permissive Unix timestamp coercion while allowing datetime objects."""

        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not _RFC3339_TIMESTAMP.fullmatch(value):
            raise ValueError("occurred_at must be an RFC3339 timestamp with a timezone")
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone_and_normalize_utc(cls, value: datetime) -> datetime:
        """Reject ambiguous naive timestamps and normalize accepted values to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def reject_non_finite_numbers(self) -> "EventEnvelope":
        """Keep the accepted envelope within PostgreSQL JSONB's numeric domain."""

        def validate(value: object) -> None:
            if isinstance(value, float) and not isfinite(value):
                raise ValueError("event JSON must not contain non-finite numbers")
            if isinstance(value, dict):
                for nested in value.values():
                    validate(nested)
            elif isinstance(value, (list, tuple)):
                for nested in value:
                    validate(nested)

        validate(self.data)
        validate(self.__pydantic_extra__ or {})
        return self
