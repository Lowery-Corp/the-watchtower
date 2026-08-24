"""Contracts for human application membership management."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ApplicationRoleName = Literal["app_admin", "viewer"]


class ApplicationMembershipRead(BaseModel):
    """One application-scoped role assignment and its grant metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    role: ApplicationRoleName
    granted_by_profile_id: UUID | None
    granted_at: datetime


class ApplicationMembershipSet(BaseModel):
    """The complete application role desired for one profile."""

    model_config = ConfigDict(extra="forbid")

    role: ApplicationRoleName
