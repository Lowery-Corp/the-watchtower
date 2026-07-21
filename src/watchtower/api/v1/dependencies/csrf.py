"""CSRF protection for ambient cookie-authenticated mutations."""

from typing import cast

from fastapi import HTTPException, Request
from starlette import status

from watchtower.core.config import Settings


def require_browser_origin(request: Request) -> None:
    """Require an explicitly trusted Origin when a browser cookie is authoritative."""

    if request.headers.getlist("Authorization"):
        return

    settings = cast(Settings, request.app.state.settings)
    if not request.cookies.get(settings.session_cookie_name):
        return

    origins = request.headers.getlist("Origin")
    if len(origins) != 1 or origins[0] not in settings.browser_allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trusted browser origin required",
        )
