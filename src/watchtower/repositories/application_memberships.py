"""PostgreSQL persistence for human application memberships."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import APP_ADMIN_ROLE_ID, VIEWER_ROLE_ID, Role

APPLICATION_MEMBERSHIP_NAMESPACE = UUID("fe2ed8dc-d070-5687-9b68-51356c0fe51f")
APPLICATION_ROLE_IDS = {"app_admin": APP_ADMIN_ROLE_ID, "viewer": VIEWER_ROLE_ID}


@dataclass(frozen=True)
class ApplicationMembershipRecord:
    """Serialized application role assignment returned by repository queries."""

    id: UUID
    profile_id: UUID
    role: str
    granted_by_profile_id: UUID | None
    granted_at: datetime


def application_membership_assignment_id(
    *, application_id: UUID, profile_id: UUID, role: str
) -> UUID:
    """Derive UUIDv5 from the application, profile, and application role."""

    return uuid5(APPLICATION_MEMBERSHIP_NAMESPACE, f"{application_id}:{profile_id}:{role}")


def membership_record(assignment: ProfileRole, role: str) -> ApplicationMembershipRecord:
    return ApplicationMembershipRecord(
        id=assignment.id,
        profile_id=assignment.profile_id,
        role=role,
        granted_by_profile_id=assignment.granted_by_profile_id,
        granted_at=assignment.granted_at,
    )


async def list_application_memberships(
    session: AsyncSession,
    *,
    application_id: UUID,
) -> list[ApplicationMembershipRecord]:
    """List application-scoped assignments without committing the caller's transaction."""

    rows = (
        await session.execute(
            select(ProfileRole, Role.name)
            .join(Role, Role.id == ProfileRole.role_id)
            .where(
                ProfileRole.application_id == application_id,
                ProfileRole.role_scope_kind == "application",
                Role.scope_kind == "application",
            )
            .order_by(ProfileRole.profile_id, Role.name, ProfileRole.id)
        )
    ).all()
    return [membership_record(assignment, role_name) for assignment, role_name in rows]


async def get_profile_application_assignments(
    session: AsyncSession, *, application_id: UUID, profile_id: UUID
) -> list[tuple[ProfileRole, str]]:
    rows = (
        await session.execute(
            select(ProfileRole, Role.name)
            .join(Role, Role.id == ProfileRole.role_id)
            .where(
                ProfileRole.application_id == application_id,
                ProfileRole.profile_id == profile_id,
                ProfileRole.role_scope_kind == "application",
                Role.scope_kind == "application",
            )
            .order_by(Role.name, ProfileRole.id)
        )
    ).all()
    return [(assignment, role_name) for assignment, role_name in rows]


async def create_application_membership(
    session: AsyncSession,
    *,
    application_id: UUID,
    profile_id: UUID,
    role: str,
    granted_by_profile_id: UUID,
) -> ProfileRole:
    assignment = ProfileRole(
        id=application_membership_assignment_id(
            application_id=application_id, profile_id=profile_id, role=role
        ),
        profile_id=profile_id,
        role_id=APPLICATION_ROLE_IDS[role],
        role_scope_kind="application",
        application_id=application_id,
        granted_by_profile_id=granted_by_profile_id,
    )
    session.add(assignment)
    await session.flush()
    await session.refresh(assignment)
    return assignment


async def delete_application_assignments(
    session: AsyncSession, *, assignment_ids: list[UUID]
) -> None:
    if assignment_ids:
        await session.execute(delete(ProfileRole).where(ProfileRole.id.in_(assignment_ids)))


async def count_application_admins(session: AsyncSession, *, application_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(ProfileRole)
        .where(
            ProfileRole.application_id == application_id,
            ProfileRole.role_id == APP_ADMIN_ROLE_ID,
            ProfileRole.role_scope_kind == "application",
        )
    )
    return int(count or 0)
