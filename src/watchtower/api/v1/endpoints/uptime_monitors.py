"""Authenticated website uptime monitor management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from watchtower.api.v1.dependencies.csrf import require_browser_origin
from watchtower.api.v1.dependencies.user_auth import CurrentProfile, get_current_profile
from watchtower.db.dependencies import get_db_session
from watchtower.repositories.website_monitors import WebsiteMonitorView
from watchtower.schemas.website_monitor import WebsiteMonitorCreate, WebsiteMonitorRead
from watchtower.services.website_monitors import (
    WebsiteMonitorAccessDeniedError,
    WebsiteMonitorConflictError,
    WebsiteMonitorLimitError,
    WebsiteMonitorServiceNotFoundError,
    create_website_monitor,
    deactivate_website_monitor,
    list_website_monitors,
)

router = APIRouter(
    prefix="/uptime-monitors",
    tags=["uptime-monitors"],
    responses={403: {"description": "Application access denied"}},
)


def _read(view: WebsiteMonitorView) -> WebsiteMonitorRead:
    monitor = view.monitor
    return WebsiteMonitorRead(
        id=monitor.id,
        service_id=monitor.service_id,
        service_slug=view.service_slug,
        service_display_name=view.service_display_name,
        url=monitor.url,
        active=monitor.active,
        last_checked_at=monitor.last_checked_at,
        last_is_up=monitor.last_is_up,
        last_status_code=monitor.last_status_code,
        last_response_time_ms=monitor.last_response_time_ms,
        uptime_24h_percent=view.uptime_24h_percent,
        created_at=monitor.created_at,
        updated_at=monitor.updated_at,
    )


@router.post(
    "",
    response_model=WebsiteMonitorRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_browser_origin)],
    responses={
        401: {"description": "Authentication required"},
        404: {"description": "Service not found"},
        409: {"description": "URL already monitored for service"},
    },
)
async def create_monitor(
    request: Request,
    payload: WebsiteMonitorCreate,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebsiteMonitorRead:
    """Create a monitor from exactly one URL and existing service."""

    try:
        return _read(
            await create_website_monitor(
                session,
                profile_id=current.profile.id,
                payload=payload,
                max_active_monitors_per_profile=(
                    request.app.state.settings.uptime_max_active_monitors_per_profile
                ),
            )
        )
    except WebsiteMonitorLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Active website monitor limit reached",
        ) from exc
    except WebsiteMonitorAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    except WebsiteMonitorServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        ) from exc
    except WebsiteMonitorConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="URL already monitored for service",
        ) from exc


@router.get("", response_model=list[WebsiteMonitorRead])
async def list_monitors(
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[WebsiteMonitorRead]:
    """List monitors on applications the profile may read."""

    return [
        _read(view)
        for view in await list_website_monitors(
            session, profile_id=current.profile.id
        )
    ]


@router.delete(
    "/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_browser_origin)],
    responses={401: {"description": "Authentication required"}},
)
async def delete_monitor(
    monitor_id: UUID,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Deactivate one monitor without deleting its history."""

    try:
        await deactivate_website_monitor(
            session, profile_id=current.profile.id, monitor_id=monitor_id
        )
    except WebsiteMonitorAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
