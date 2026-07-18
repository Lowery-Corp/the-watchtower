"""Monitored service persistence operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.monitored_service import MonitoredService


async def create_monitored_service(
    session: AsyncSession,
    *,
    slug: str,
    display_name: str,
    environment: str,
    secret_key_id: str,
    active: bool = True,
) -> MonitoredService:
    """Add a source identity without committing the caller's transaction."""

    service = MonitoredService(
        slug=slug,
        display_name=display_name,
        environment=environment,
        active=active,
        secret_key_id=secret_key_id,
    )
    session.add(service)
    await session.flush()
    return service


async def get_monitored_service_by_slug(
    session: AsyncSession,
    slug: str,
) -> MonitoredService | None:
    """Return a monitored service by its stable source slug."""

    result = await session.execute(
        select(MonitoredService).where(MonitoredService.slug == slug)
    )
    return result.scalar_one_or_none()
