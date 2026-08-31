"""Application-authorized website monitor use cases."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.repositories.monitored_services import (
    get_application_by_id,
    has_application_permission,
)
from watchtower.repositories.website_monitors import (
    WebsiteMonitorView,
    add_website_monitor,
    enforce_active_monitor_quota,
    get_authorized_website_monitor,
    get_website_monitor_by_service_url,
    get_website_monitor_uptime_24h,
    list_authorized_website_monitors,
)
from watchtower.schemas.website_monitor import WebsiteMonitorCreate


class WebsiteMonitorAccessDeniedError(PermissionError):
    """The profile lacks the required application permission."""


class WebsiteMonitorServiceNotFoundError(LookupError):
    """The associated service does not exist."""


class WebsiteMonitorLimitError(ValueError):
    """The profile has reached its active monitor quota."""


class WebsiteMonitorConflictError(ValueError):
    """The service already has the canonical URL configured."""


def _constraint_name(exc: IntegrityError) -> str | None:
    for candidate in (exc.orig, getattr(exc.orig, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str):
            return name
    return None


async def create_website_monitor(
    session: AsyncSession,
    *,
    profile_id: UUID,
    payload: WebsiteMonitorCreate,
    max_active_monitors_per_profile: int = 100,
) -> WebsiteMonitorView:
    """Create one immediately due monitor in a single transaction."""

    try:
        async with session.begin():
            allowed = await has_application_permission(
                session,
                profile_id=profile_id,
                application_id=payload.service_id,
                permission_name="applications.manage",
            )
            if not allowed:
                raise WebsiteMonitorAccessDeniedError("Application access denied")
            service = await get_application_by_id(
                session, application_id=payload.service_id
            )
            if service is None:
                raise WebsiteMonitorServiceNotFoundError("Service not found")
            monitor = await get_website_monitor_by_service_url(
                session, service_id=service.id, url=payload.url
            )
            if monitor is not None and monitor.active:
                raise WebsiteMonitorConflictError(
                    "URL already monitored for service"
                )
            try:
                await enforce_active_monitor_quota(
                    session,
                    profile_id=profile_id,
                    maximum=max_active_monitors_per_profile,
                )
            except OverflowError as exc:
                raise WebsiteMonitorLimitError(str(exc)) from exc
            if monitor is not None:
                now = datetime.now(UTC)
                monitor.active = True
                monitor.next_check_at = now
                monitor.updated_at = now
                await session.flush()
            else:
                monitor = await add_website_monitor(
                    session, service_id=service.id, url=payload.url
                )
            return WebsiteMonitorView(
                monitor=monitor,
                service_slug=service.slug,
                service_display_name=service.display_name,
                uptime_24h_percent=await get_website_monitor_uptime_24h(
                    session, monitor_id=monitor.id
                ),
            )
    except IntegrityError as exc:
        if _constraint_name(exc) != "uq_website_monitor_service_url":
            raise
        raise WebsiteMonitorConflictError("URL already monitored for service") from exc


async def list_website_monitors(
    session: AsyncSession, *, profile_id: UUID
) -> list[WebsiteMonitorView]:
    """List active monitors authorized by applications.read."""

    async with session.begin():
        return await list_authorized_website_monitors(
            session, profile_id=profile_id
        )


async def deactivate_website_monitor(
    session: AsyncSession, *, profile_id: UUID, monitor_id: UUID
) -> None:
    """Deactivate a monitor after aggregate application authorization."""

    async with session.begin():
        monitor = await get_authorized_website_monitor(
            session,
            profile_id=profile_id,
            monitor_id=monitor_id,
            permission_name="applications.manage",
        )
        if monitor is None:
            raise WebsiteMonitorAccessDeniedError("Application access denied")
        monitor.active = False
        await session.flush()
