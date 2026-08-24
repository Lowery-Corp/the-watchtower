"""Profile-scoped monitored-service persistence operations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.monitored_service import MonitoredService


async def create_monitored_service(
    session: AsyncSession,
    *,
    profile_id: UUID,
    slug: str,
    display_name: str,
    environment: str,
    secret_key_id: str = "managed",
    active: bool = True,
) -> MonitoredService:
    """Add a profile-owned source without committing the caller's transaction."""

    service = MonitoredService(
        profile_id=profile_id,
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
    *,
    profile_id: UUID,
    slug: str,
) -> MonitoredService | None:
    """Return a service only inside the requested profile."""

    return (
        await session.scalars(
            select(MonitoredService).where(
                MonitoredService.profile_id == profile_id,
                MonitoredService.slug == slug,
            )
        )
    ).one_or_none()


async def get_monitored_service_by_id(
    session: AsyncSession,
    *,
    profile_id: UUID,
    service_id: UUID,
) -> MonitoredService | None:
    """Return a service by ID without crossing a profile boundary."""

    return (
        await session.scalars(
            select(MonitoredService).where(
                MonitoredService.profile_id == profile_id,
                MonitoredService.id == service_id,
            )
        )
    ).one_or_none()


async def list_monitored_services(
    session: AsyncSession,
    *,
    profile_id: UUID,
) -> list[MonitoredService]:
    """List one profile's services in deterministic creation order."""

    result = await session.scalars(
        select(MonitoredService)
        .where(MonitoredService.profile_id == profile_id)
        .order_by(MonitoredService.created_at, MonitoredService.id)
    )
    return list(result.all())
