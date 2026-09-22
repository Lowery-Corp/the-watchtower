"""Machine-facing profile uptime endpoint."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.core.api_keys import ApiKeyFormatError, parse_profile_api_key
from watchtower.core.config import Settings
from watchtower.db.dependencies import get_db_session
from watchtower.schemas.profile_uptime import ProfileUptimeResponse
from watchtower.services.profile_uptime import (
    ProfileUptimeAuthenticationError,
    ProfileUptimeRateLimited,
    ProfileUptimeSuspendedError,
    read_profile_uptime,
)

router = APIRouter(tags=["uptime"])
_GENERIC_AUTH_ERROR = "Invalid profile uptime authentication"
_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Invalid profile uptime authentication"},
    status.HTTP_403_FORBIDDEN: {"description": "Profile is suspended"},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "description": "Profile uptime request budget exceeded",
        "headers": {
            "Retry-After": {
                "description": "Seconds until the profile-key budget resets",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    },
}
_OPENAPI_EXTRA: dict[str, Any] = {
    "parameters": [
        {
            "name": "X-Watchtower-Profile-Key",
            "in": "header",
            "required": True,
            "description": "Profile uptime machine credential",
            "schema": {
                "type": "string",
                "pattern": r"^wtp_v1_[A-Za-z0-9_-]{16}\.[A-Za-z0-9_-]{43}$",
            },
        }
    ]
}


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_GENERIC_AUTH_ERROR,
    )


@router.get(
    "/uptime",
    response_model=ProfileUptimeResponse,
    responses=_RESPONSES,
    openapi_extra=_OPENAPI_EXTRA,
)
async def get_profile_uptime(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProfileUptimeResponse:
    """Return uptime state visible to the profile derived from one machine key."""

    values = request.headers.getlist("X-Watchtower-Profile-Key")
    if len(values) != 1:
        raise _unauthorized()
    token = values[0]
    try:
        parsed = parse_profile_api_key(token)
    except ApiKeyFormatError as exc:
        raise _unauthorized() from exc

    settings = cast(Settings, request.app.state.settings)
    try:
        outcome = await read_profile_uptime(
            session,
            token=token,
            public_prefix=parsed.public_prefix,
            max_requests=settings.uptime_api_rate_limit_requests,
            window_seconds=settings.uptime_api_rate_limit_window_seconds,
        )
    except ProfileUptimeAuthenticationError as exc:
        raise _unauthorized() from exc
    except ProfileUptimeSuspendedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Profile is suspended",
        ) from exc
    if isinstance(outcome, ProfileUptimeRateLimited):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Profile uptime rate limit exceeded",
            headers={"Retry-After": str(outcome.retry_after)},
        )
    response.headers["Cache-Control"] = "no-store"
    return outcome
