"""User-session authentication dependencies."""

from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from watchtower.clients.auth_service import (
    AuthServiceClient,
    AuthServiceProtocolError,
    AuthServiceRateLimited,
    AuthServiceUnauthorized,
    AuthServiceUnavailable,
)
from watchtower.db.dependencies import get_db_session
from watchtower.models.profile import Profile
from watchtower.schemas.auth import AuthenticatedUser
from watchtower.services.profiles import provision_profile_for_user


@dataclass(frozen=True)
class AuthenticatedRequest:
    """Validated user identity plus its bearer token."""

    user: AuthenticatedUser
    token: str

    def __repr__(self) -> str:
        return f"AuthenticatedRequest(user={self.user!r}, token=SecretStr('**********'))"


def get_session_token(request: Request) -> str:
    """Read a browser cookie or explicit bearer token without accepting empties."""

    settings = request.app.state.settings
    authorization_values = request.headers.getlist("Authorization")
    if len(authorization_values) > 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if authorization_values:
        scheme, separator, credentials = authorization_values[0].partition(" ")
        if separator and scheme.lower() == "bearer" and credentials:
            return credentials
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = request.cookies.get(settings.session_cookie_name)
    if token:
        return token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_authenticated_request(
    request: Request,
    token: Annotated[str, Depends(get_session_token)],
) -> AuthenticatedRequest:
    """Validate the external session and fail closed on upstream problems."""

    client = cast(AuthServiceClient, request.app.state.auth_client)
    try:
        user = await client.get_current_user(token)
    except AuthServiceUnauthorized as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthServiceRateLimited as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Authentication service rate limited",
            headers=headers,
        ) from exc
    except AuthServiceUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc
    except AuthServiceProtocolError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service returned an invalid response",
        ) from exc
    return AuthenticatedRequest(user=user, token=token)


@dataclass(frozen=True)
class CurrentProfile:
    """Validated identity joined to its local tenant root."""

    authenticated: AuthenticatedRequest
    profile: Profile


async def get_current_profile(
    authenticated: Annotated[AuthenticatedRequest, Depends(get_authenticated_request)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentProfile:
    """Provision and return the caller's profile."""

    profile = await provision_profile_for_user(session, authenticated.user)
    return CurrentProfile(authenticated=authenticated, profile=profile)
