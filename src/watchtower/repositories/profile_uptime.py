"""Authorized uptime aggregation queries for profile machine clients."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.monitored_service import MonitoredService
from watchtower.models.website_monitor import WebsiteMonitor
from watchtower.models.website_monitor_check import WebsiteMonitorCheck
from watchtower.repositories.monitored_services import application_permission_exists


@dataclass(frozen=True, slots=True)
class MonitorUptimeView:
    monitor: WebsiteMonitor
    uptime_24h_percent: float | None


@dataclass(frozen=True, slots=True)
class ServiceUptimeView:
    service: MonitoredService
    monitors: tuple[MonitorUptimeView, ...]


async def list_profile_uptime(
    session: AsyncSession,
    *,
    profile_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[ServiceUptimeView]:
    """Return every readable service with active monitors and 24-hour rollups."""

    total = func.count(WebsiteMonitorCheck.id)
    up = func.count(WebsiteMonitorCheck.id).filter(WebsiteMonitorCheck.is_up.is_(True))
    uptime = case((total == 0, None), else_=(up * 100.0) / total).label(
        "uptime_24h_percent"
    )
    rows = (
        await session.execute(
            select(MonitoredService, WebsiteMonitor, uptime)
            .outerjoin(
                WebsiteMonitor,
                and_(
                    WebsiteMonitor.service_id == MonitoredService.id,
                    WebsiteMonitor.active.is_(True),
                ),
            )
            .outerjoin(
                WebsiteMonitorCheck,
                and_(
                    WebsiteMonitorCheck.monitor_id == WebsiteMonitor.id,
                    WebsiteMonitorCheck.checked_at >= window_start,
                    WebsiteMonitorCheck.checked_at <= window_end,
                ),
            )
            .where(
                application_permission_exists(
                    profile_id=profile_id,
                    application_id=MonitoredService.id,
                    permission_name="applications.read",
                )
            )
            .group_by(MonitoredService.id, WebsiteMonitor.id)
            .order_by(
                MonitoredService.created_at,
                MonitoredService.id,
                WebsiteMonitor.created_at.nulls_last(),
                WebsiteMonitor.id.nulls_last(),
            )
        )
    ).all()

    grouped: list[ServiceUptimeView] = []
    current_service: MonitoredService | None = None
    current_monitors: list[MonitorUptimeView] = []
    for service, monitor, uptime_value in rows:
        if current_service is None or service.id != current_service.id:
            if current_service is not None:
                grouped.append(
                    ServiceUptimeView(
                        service=current_service,
                        monitors=tuple(current_monitors),
                    )
                )
            current_service = service
            current_monitors = []
        if monitor is not None:
            current_monitors.append(
                MonitorUptimeView(
                    monitor=monitor,
                    uptime_24h_percent=(
                        round(float(uptime_value), 2) if uptime_value is not None else None
                    ),
                )
            )
    if current_service is not None:
        grouped.append(
            ServiceUptimeView(service=current_service, monitors=tuple(current_monitors))
        )
    return grouped
