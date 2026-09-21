"""External-auth session and current-user endpoints."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from watchtower.api.v1.dependencies.csrf import require_browser_origin
from watchtower.api.v1.dependencies.user_auth import (
    CurrentProfile,
    get_current_profile,
    get_session_token,
)
from watchtower.clients.auth_service import (
    AuthServiceClient,
    AuthServiceProtocolError,
    AuthServiceRateLimited,
    AuthServiceUnauthorized,
    AuthServiceUnavailable,
)
from watchtower.db.dependencies import get_db_session
from watchtower.schemas.auth import CurrentUserResponse, LoginRequest
from watchtower.services.profiles import (
    ProfileAccessDeniedError,
    provision_profile_for_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "Invalid credentials"},
        403: {"description": "Profile access denied"},
        503: {"description": "Auth unavailable"},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Create a browser session using the external auth service."""

    client = cast(AuthServiceClient, request.app.state.auth_client)
    try:
        session = await client.login(
            email=payload.email,
            password=payload.password.get_secret_value(),
        )
    except AuthServiceUnauthorized as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
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

    try:
        await provision_profile_for_user(db_session, session.user)
    except ProfileAccessDeniedError as exc:
        try:
            await client.logout(session.token.get_secret_value())
        except (
            AuthServiceUnauthorized,
            AuthServiceRateLimited,
            AuthServiceUnavailable,
            AuthServiceProtocolError,
        ):
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Profile access denied",
        ) from exc

    settings = request.app.state.settings
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session.token.get_secret_value(),
        max_age=settings.session_cookie_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_same_site,
        path="/",
    )
    return response


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Profile access denied"},
        503: {"description": "Auth unavailable"},
    },
)
async def current_user(
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
) -> CurrentUserResponse:
    """Return the live external identity and its active local profile."""

    return CurrentUserResponse(
        id=current.authenticated.user.id,
        username=current.authenticated.user.username,
        is_admin=current.authenticated.user.is_admin,
        profile_id=current.profile.id,
        display_name=current.profile.display_name,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_browser_origin)],
    responses={401: {"description": "Authentication required"}},
)
async def logout(
    request: Request,
    token: Annotated[str, Depends(get_session_token)],
) -> Response:
    """Attempt upstream invalidation and always clear the local cookie."""

    client = cast(AuthServiceClient, request.app.state.auth_client)
    response_status = status.HTTP_204_NO_CONTENT
    response_headers: dict[str, str] = {}
    try:
        await client.logout(token)
    except AuthServiceUnauthorized:
        pass
    except AuthServiceRateLimited as exc:
        response_status = status.HTTP_429_TOO_MANY_REQUESTS
        if exc.retry_after:
            response_headers["Retry-After"] = str(exc.retry_after)
    except AuthServiceUnavailable:
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
    except AuthServiceProtocolError:
        response_status = status.HTTP_502_BAD_GATEWAY

    settings = request.app.state.settings
    response = Response(status_code=response_status, headers=response_headers)
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_same_site,
        path="/",
    )
    return response
