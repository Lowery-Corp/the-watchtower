"""Profile-scoped monitored-service use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.monitored_service import MonitoredService
from watchtower.repositories.monitored_services import (
    create_creator_app_admin_assignment,
    create_monitored_service,
    get_application_by_id,
    has_application_permission,
    list_authorized_monitored_services,
)
from watchtower.schemas.monitored_service import (
    MonitoredServiceCreate,
    MonitoredServiceUpdate,
)


class MonitoredServiceNotFoundError(LookupError):
    """The service does not exist inside the authenticated profile."""


class MonitoredServiceConflictError(ValueError):
    """The profile already owns a service with the requested slug."""


class ApplicationAccessDeniedError(PermissionError):
    """The profile lacks the required permission on an application."""


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    """Extract a PostgreSQL constraint name without depending on driver internals."""

    for candidate in (exc.orig, getattr(exc.orig, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str):
            return name
    return None


async def _require_application_permission(
    session: AsyncSession,
    *,
    profile_id: UUID,
    application_id: UUID,
    permission_name: str,
) -> None:
    """Enforce one PostgreSQL-backed application permission."""

    if not await has_application_permission(
        session,
        profile_id=profile_id,
        application_id=application_id,
        permission_name=permission_name,
    ):
        raise ApplicationAccessDeniedError("Application access denied")


async def create_service(
    session: AsyncSession,
    *,
    profile_id: UUID,
    payload: MonitoredServiceCreate,
) -> MonitoredService:
    """Create a profile-owned service in one transaction."""

    try:
        async with session.begin():
            service = await create_monitored_service(
                session,
                profile_id=profile_id,
                slug=payload.slug,
                display_name=payload.display_name,
                environment=payload.environment,
            )
            await create_creator_app_admin_assignment(
                session,
                profile_id=profile_id,
                application_id=service.id,
            )
            return service
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != "uq_monitored_service_profile_slug":
            raise
        raise MonitoredServiceConflictError("Service slug already exists") from exc


async def list_services(
    session: AsyncSession,
    *,
    profile_id: UUID,
) -> list[MonitoredService]:
    """List exactly the applications readable by the current profile."""

    async with session.begin():
        return await list_authorized_monitored_services(
            session,
            profile_id=profile_id,
            permission_name="applications.read",
        )


async def get_service(
    session: AsyncSession,
    *,
    profile_id: UUID,
    service_id: UUID,
) -> MonitoredService:
    """Fetch an application after enforcing applications.read."""

    async with session.begin():
        await _require_application_permission(
            session,
            profile_id=profile_id,
            application_id=service_id,
            permission_name="applications.read",
        )
        service = await get_application_by_id(session, application_id=service_id)
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
    """Update an application after enforcing applications.manage."""

    async with session.begin():
        await _require_application_permission(
            session,
            profile_id=profile_id,
            application_id=service_id,
            permission_name="applications.manage",
        )
        service = await get_application_by_id(session, application_id=service_id)
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
    """Deactivate an application after enforcing applications.manage."""

    async with session.begin():
        await _require_application_permission(
            session,
            profile_id=profile_id,
            application_id=service_id,
            permission_name="applications.manage",
        )
        service = await get_application_by_id(session, application_id=service_id)
        if service is None:
            raise MonitoredServiceNotFoundError("Service not found")
        service.active = False
        await session.flush()
