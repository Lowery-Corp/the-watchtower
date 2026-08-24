"""Human application membership management use cases."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.repositories.application_memberships import (
    ApplicationMembershipRecord,
    count_application_admins,
    create_application_membership,
    delete_application_assignments,
    get_profile_application_assignments,
    membership_record,
)
from watchtower.repositories.application_memberships import (
    list_application_memberships as list_membership_records,
)
from watchtower.repositories.monitored_services import (
    get_application_by_id,
    has_application_permission,
)


class ApplicationNotFoundError(LookupError):
    """The requested application does not exist."""


class ApplicationAccessDeniedError(PermissionError):
    """The caller cannot manage memberships on the application."""


class ProfileNotFoundError(LookupError):
    """The requested local target profile does not exist."""


class LastApplicationAdminError(RuntimeError):
    """A mutation would leave the application without a local app_admin."""


async def _require_membership_manager(
    session: AsyncSession,
    *,
    profile_id: UUID,
    application_id: UUID,
) -> None:
    if not await has_application_permission(
        session,
        profile_id=profile_id,
        application_id=application_id,
        permission_name="memberships.manage",
    ):
        raise ApplicationAccessDeniedError("Application access denied")


async def list_application_memberships(
    session: AsyncSession,
    *,
    actor_profile_id: UUID,
    application_id: UUID,
) -> list[ApplicationMembershipRecord]:
    """List memberships after a PostgreSQL-backed authorization check."""

    async with session.begin():
        application = await get_application_by_id(session, application_id=application_id)
        if application is None:
            raise ApplicationNotFoundError("Application not found")
        await _require_membership_manager(
            session,
            profile_id=actor_profile_id,
            application_id=application_id,
        )
        return await list_membership_records(session, application_id=application_id)


async def set_application_membership(
    session: AsyncSession,
    *,
    actor_profile_id: UUID,
    application_id: UUID,
    target_profile_id: UUID,
    role: str,
) -> ApplicationMembershipRecord:
    """Set one profile's sole application role in one committed transaction."""

    async with session.begin():
        application = await session.scalar(
            select(MonitoredService).where(MonitoredService.id == application_id).with_for_update()
        )
        if application is None:
            raise ApplicationNotFoundError("Application not found")
        await _require_membership_manager(
            session,
            profile_id=actor_profile_id,
            application_id=application_id,
        )
        if await session.get(Profile, target_profile_id) is None:
            raise ProfileNotFoundError("Profile not found")
        assignments = await get_profile_application_assignments(
            session,
            application_id=application_id,
            profile_id=target_profile_id,
        )
        desired = next(
            ((assignment, name) for assignment, name in assignments if name == role),
            None,
        )
        if role != "app_admin" and any(name == "app_admin" for _, name in assignments):
            if await count_application_admins(session, application_id=application_id) <= 1:
                raise LastApplicationAdminError("Application must retain an app_admin")
        if desired is None:
            assignment = await create_application_membership(
                session,
                application_id=application_id,
                profile_id=target_profile_id,
                role=role,
                granted_by_profile_id=actor_profile_id,
            )
        else:
            assignment = desired[0]
        await delete_application_assignments(
            session,
            assignment_ids=[item.id for item, name in assignments if name != role],
        )
        return membership_record(assignment, role)


async def remove_application_membership(
    session: AsyncSession,
    *,
    actor_profile_id: UUID,
    application_id: UUID,
    target_profile_id: UUID,
) -> None:
    """Remove all application roles for one profile while retaining a local admin."""

    async with session.begin():
        application = await session.scalar(
            select(MonitoredService).where(MonitoredService.id == application_id).with_for_update()
        )
        if application is None:
            raise ApplicationNotFoundError("Application not found")
        await _require_membership_manager(
            session,
            profile_id=actor_profile_id,
            application_id=application_id,
        )
        if await session.get(Profile, target_profile_id) is None:
            raise ProfileNotFoundError("Profile not found")
        assignments = await get_profile_application_assignments(
            session,
            application_id=application_id,
            profile_id=target_profile_id,
        )
        if any(name == "app_admin" for _, name in assignments):
            if await count_application_admins(session, application_id=application_id) <= 1:
                raise LastApplicationAdminError("Application must retain an app_admin")
        await delete_application_assignments(
            session,
            assignment_ids=[assignment.id for assignment, _ in assignments],
        )
