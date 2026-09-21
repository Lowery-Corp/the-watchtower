"""Contracts for website uptime monitors."""

from datetime import datetime
from ipaddress import ip_address
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from watchtower.uptime.probe import is_public_address

_HTTP_URL = TypeAdapter(AnyHttpUrl)


class WebsiteMonitorCreate(BaseModel):
    """Create a website monitor for an existing service with no tuning fields."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    service_id: UUID

    @field_validator("url", mode="before")
    @classmethod
    def canonicalize_url(cls, value: object) -> str:
        """Use Pydantic's strict HTTP URL parser and retain its canonical form."""

        parsed = _HTTP_URL.validate_python(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL credentials are not allowed")
        if parsed.fragment is not None:
            raise ValueError("URL fragments are not allowed")
        if parsed.port is not None:
            expected_port = 80 if parsed.scheme == "http" else 443
            if parsed.port != expected_port:
                raise ValueError("Only the default port is allowed")
        hostname = (parsed.host or "").rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("Localhost targets are not allowed")
        try:
            address = ip_address(hostname.strip("[]"))
        except ValueError:
            pass
        else:
            if not is_public_address(str(address)):
                raise ValueError("Only globally routable targets are allowed")
        return str(parsed)


class WebsiteMonitorRead(BaseModel):
    """Safe monitor state returned to browser operators."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    service_id: UUID
    service_slug: str
    service_display_name: str
    url: str
    active: bool
    last_checked_at: datetime | None
    last_is_up: bool | None
    last_status_code: int | None
    last_response_time_ms: int | None
    uptime_24h_percent: float | None
    created_at: datetime
    updated_at: datetime


class WebsiteMonitorStatus(BaseModel):
    """Internal latest-status shape shared by API and worker tests."""

    state: Literal["pending", "up", "down"]
