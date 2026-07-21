"""Typed contracts for external identities and Watchtower sessions."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthenticatedUser(BaseModel):
    """Stable external identity used to resolve a Watchtower profile."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: UUID
    username: str = Field(min_length=1, max_length=255)
    is_admin: bool


class AuthenticatedSession(BaseModel):
    """Authenticated identity and redacted bearer token."""

    model_config = ConfigDict(frozen=True)

    user: AuthenticatedUser
    token: SecretStr


class LoginRequest(BaseModel):
    """Credentials forwarded to, but never retained by, the auth service."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: SecretStr


class AuthUserResponse(BaseModel):
    """Sanitized identity response with no bearer token."""

    id: UUID
    username: str
    is_admin: bool


class CurrentUserResponse(AuthUserResponse):
    """External identity joined to its Watchtower profile."""

    profile_id: UUID
    display_name: str | None
