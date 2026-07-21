"""Profile-scoped monitored-service use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.monitored_service import MonitoredService
from watchtower.repositories.monitored_services import (
    create_monitored_service,
    get_monitored_service_by_id,
    list_monitored_services,
)
from watchtower.schemas.monitored_service import (
    MonitoredServiceCreate,
    MonitoredServiceUpdate,
)


class MonitoredServiceNotFoundError(LookupError):
    """The service does not exist inside the authenticated profile."""


class MonitoredServiceConflictError(ValueError):
    """The profile already owns a service with the requested slug."""


async def create_service(
    session: AsyncSession,
    *,
    profile_id: UUID,
    payload: MonitoredServiceCreate,
) -> MonitoredService:
    """Create a profile-owned service in one transaction."""

    try:
        async with session.begin():
            return await create_monitored_service(
                session,
                profile_id=profile_id,
                slug=payload.slug,
                display_name=payload.display_name,
                environment=payload.environment,
            )
    except IntegrityError as exc:
        raise MonitoredServiceConflictError("Service slug already exists") from exc


async def list_services(
    session: AsyncSession,
    *,
    profile_id: UUID,
) -> list[MonitoredService]:
    """List a profile's services under a read transaction."""

    async with session.begin():
        return await list_monitored_services(session, profile_id=profile_id)


async def get_service(
    session: AsyncSession,
    *,
    profile_id: UUID,
    service_id: UUID,
) -> MonitoredService:
    """Fetch a service without revealing cross-profile existence."""

    async with session.begin():
        service = await get_monitored_service_by_id(
            session, profile_id=profile_id, service_id=service_id
        )
    if service is None:
        raise MonitoredServiceNotFoundError("Service not found")
    return service


async def update_service(
    session: AsyncSession,
    *,
    profile_id: UUID,
    service_id: UUID,
    payload: MonitoredServiceUpdate,
) -> MonitoredService:
    """Update mutable metadata for one owned service."""

    async with session.begin():
        service = await get_monitored_service_by_id(
            session, profile_id=profile_id, service_id=service_id
        )
        if service is None:
            raise MonitoredServiceNotFoundError("Service not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(service, field, value)
        await session.flush()
        await session.refresh(service)
        return service


async def deactivate_service(
    session: AsyncSession,
    *,
    profile_id: UUID,
    service_id: UUID,
) -> None:
    """Soft-delete a service while preserving immutable event history."""

    async with session.begin():
        service = await get_monitored_service_by_id(
            session, profile_id=profile_id, service_id=service_id
        )
        if service is None:
            raise MonitoredServiceNotFoundError("Service not found")
        service.active = False
        await session.flush()
