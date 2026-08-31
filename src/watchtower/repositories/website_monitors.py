"""Persistence queries for profile-authorized website monitors."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, case, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.monitored_service import MonitoredService
from watchtower.models.website_monitor import WebsiteMonitor
from watchtower.models.website_monitor_check import WebsiteMonitorCheck
from watchtower.repositories.monitored_services import application_permission_exists
from watchtower.uptime.probe import ProbeResult


@dataclass(frozen=True)
class WebsiteMonitorView:
    """One monitor joined to safe service display data and rolling uptime."""

    monitor: WebsiteMonitor
    service_slug: str
    service_display_name: str
    uptime_24h_percent: float | None


async def enforce_active_monitor_quota(
    session: AsyncSession, *, profile_id: UUID, maximum: int
) -> None:
    """Serialize and enforce a profile-wide active monitor quota."""

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": f"uptime-monitor-quota:{profile_id}"},
    )
    count = await session.scalar(
        select(func.count(WebsiteMonitor.id))
        .join(MonitoredService, MonitoredService.id == WebsiteMonitor.service_id)
        .where(
            MonitoredService.profile_id == profile_id,
            WebsiteMonitor.active.is_(True),
        )
    )
    if int(count or 0) >= maximum:
        raise OverflowError("Active website monitor limit reached")


async def add_website_monitor(
    session: AsyncSession, *, service_id: UUID, url: str
) -> WebsiteMonitor:
    """Add a due monitor without committing the caller's transaction."""

    monitor = WebsiteMonitor(service_id=service_id, url=url)
    session.add(monitor)
    await session.flush()
    await session.refresh(monitor)
    return monitor


async def get_website_monitor_by_service_url(
    session: AsyncSession, *, service_id: UUID, url: str
) -> WebsiteMonitor | None:
    """Lock an existing service/URL monitor, including inactive rows."""

    return cast(
        WebsiteMonitor | None,
        await session.scalar(
            select(WebsiteMonitor)
            .where(
                WebsiteMonitor.service_id == service_id,
                WebsiteMonitor.url == url,
            )
            .with_for_update()
        ),
    )


async def get_website_monitor_uptime_24h(
    session: AsyncSession, *, monitor_id: UUID
) -> float | None:
    """Calculate rolling 24-hour uptime for one monitor."""

    window_start = datetime.now(UTC) - timedelta(hours=24)
    total = func.count(WebsiteMonitorCheck.id)
    up = func.count(WebsiteMonitorCheck.id).filter(
        WebsiteMonitorCheck.is_up.is_(True)
    )
    value = await session.scalar(
        select(case((total == 0, None), else_=(up * 100.0) / total)).where(
            WebsiteMonitorCheck.monitor_id == monitor_id,
            WebsiteMonitorCheck.checked_at >= window_start,
        )
    )
    return round(float(value), 2) if value is not None else None


async def get_authorized_website_monitor(
    session: AsyncSession,
    *,
    profile_id: UUID,
    monitor_id: UUID,
    permission_name: str,
) -> WebsiteMonitor | None:
    """Fetch a monitor only when the profile has its application permission."""

    return cast(
        WebsiteMonitor | None,
        await session.scalar(
            select(WebsiteMonitor).where(
            WebsiteMonitor.id == monitor_id,
            application_permission_exists(
                profile_id=profile_id,
                application_id=WebsiteMonitor.service_id,
                permission_name=permission_name,
                ),
            )
        ),
    )


async def list_authorized_website_monitors(
    session: AsyncSession, *, profile_id: UUID
) -> list[WebsiteMonitorView]:
    """List active monitors on applications readable by one profile."""

    window_start = datetime.now(UTC) - timedelta(hours=24)
    total = func.count(WebsiteMonitorCheck.id).filter(
        WebsiteMonitorCheck.checked_at >= window_start
    )
    up = func.count(WebsiteMonitorCheck.id).filter(
        WebsiteMonitorCheck.checked_at >= window_start,
        WebsiteMonitorCheck.is_up.is_(True),
    )
    uptime = case(
        (total == 0, None),
        else_=(up * 100.0) / total,
    ).label("uptime_24h_percent")
    rows = (
        await session.execute(
            select(
                WebsiteMonitor,
                MonitoredService.slug,
                MonitoredService.display_name,
                uptime,
            )
            .join(MonitoredService, MonitoredService.id == WebsiteMonitor.service_id)
            .outerjoin(
                WebsiteMonitorCheck,
                and_(
                    WebsiteMonitorCheck.monitor_id == WebsiteMonitor.id,
                    WebsiteMonitorCheck.checked_at >= window_start,
                ),
            )
            .where(
                WebsiteMonitor.active.is_(True),
                application_permission_exists(
                    profile_id=profile_id,
                    application_id=WebsiteMonitor.service_id,
                    permission_name="applications.read",
                ),
            )
            .group_by(WebsiteMonitor.id, MonitoredService.id)
            .order_by(WebsiteMonitor.created_at, WebsiteMonitor.id)
        )
    ).all()
    return [
        WebsiteMonitorView(
            monitor=monitor,
            service_slug=slug,
            service_display_name=display_name,
            uptime_24h_percent=(
                round(float(uptime_value), 2) if uptime_value is not None else None
            ),
        )
        for monitor, slug, display_name, uptime_value in rows
    ]


@dataclass(frozen=True)
class ClaimedWebsiteMonitor:
    """Minimum immutable work item released from the claim transaction."""

    id: UUID
    url: str


async def claim_due_website_monitors(
    session: AsyncSession,
    *,
    now: datetime,
    interval_seconds: int,
    limit: int,
) -> list[ClaimedWebsiteMonitor]:
    """Claim due rows with skip-locked semantics and advance their schedule."""

    monitors = list(
        await session.scalars(
            select(WebsiteMonitor)
            .where(
                WebsiteMonitor.active.is_(True),
                WebsiteMonitor.next_check_at <= now,
            )
            .order_by(WebsiteMonitor.next_check_at, WebsiteMonitor.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    next_check_at = now + timedelta(seconds=interval_seconds)
    for monitor in monitors:
        monitor.next_check_at = next_check_at
        monitor.updated_at = now
    await session.flush()
    return [ClaimedWebsiteMonitor(id=monitor.id, url=monitor.url) for monitor in monitors]


async def website_monitor_is_active(
    session: AsyncSession, *, monitor_id: UUID
) -> bool:
    """Return whether a claimed monitor is still active before probing."""

    return bool(
        await session.scalar(
            select(WebsiteMonitor.active).where(WebsiteMonitor.id == monitor_id)
        )
    )


async def record_website_monitor_check(
    session: AsyncSession,
    *,
    monitor_id: UUID,
    checked_at: datetime,
    result: ProbeResult,
) -> bool:
    """Append a result only while the monitor remains active."""

    monitor = await session.get(WebsiteMonitor, monitor_id, with_for_update=True)
    if monitor is None:
        raise LookupError("Website monitor no longer exists")
    if not monitor.active:
        return False
    session.add(
        WebsiteMonitorCheck(
            monitor_id=monitor_id,
            checked_at=checked_at,
            is_up=result.is_up,
            status_code=result.status_code,
            response_time_ms=result.response_time_ms,
            failure_kind=result.failure_kind,
        )
    )
    monitor.last_checked_at = checked_at
    monitor.last_is_up = result.is_up
    monitor.last_status_code = result.status_code
    monitor.last_response_time_ms = result.response_time_ms
    monitor.last_failure_kind = result.failure_kind
    monitor.updated_at = checked_at
    await session.flush()
    return True


async def prune_website_monitor_checks(
    session: AsyncSession, *, older_than: datetime, limit: int
) -> int:
    """Delete one deterministic bounded batch of expired history."""

    expired_ids = (
        select(WebsiteMonitorCheck.id)
        .where(WebsiteMonitorCheck.checked_at < older_than)
        .order_by(WebsiteMonitorCheck.checked_at, WebsiteMonitorCheck.id)
        .limit(limit)
    )
    result = await session.execute(
        delete(WebsiteMonitorCheck).where(WebsiteMonitorCheck.id.in_(expired_ids))
    )
    rowcount = cast(Any, result).rowcount
    return int(rowcount or 0)
