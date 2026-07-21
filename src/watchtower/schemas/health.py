"""Operational response schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """A stable operational status response."""

    status: str
    service: str = "watchtower"
