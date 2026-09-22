"""Machine-facing profile uptime response contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProfileUptimeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID


class ProfileUptimeMonitor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    url: str
    status: Literal["pending", "up", "down"]
    last_checked_at: datetime | None
    status_code: int | None
    response_time_ms: int | None
    uptime_24h_percent: float | None


class ProfileUptimeService(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    display_name: str
    environment: str
    active: bool
    monitors: list[ProfileUptimeMonitor]


class ProfileUptimeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProfileUptimeIdentity
    generated_at: datetime
    services: list[ProfileUptimeService]
