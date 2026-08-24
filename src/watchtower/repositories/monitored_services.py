"""PostgreSQL persistence and authorization for monitored services."""

import hashlib
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from watchtower.models.monitored_service import MonitoredService
from watchtower.models.permission import Permission
from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import APP_ADMIN_ROLE_ID, Role
from watchtower.models.role_permission import RolePermission


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


def creator_app_admin_assignment_id(application_id: UUID) -> UUID:
    """Return the same deterministic assignment ID used by migration 0013."""

    digest = hashlib.md5(
        f"watchtower-owner-app-admin:{application_id}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return UUID(digest)


async def create_creator_app_admin_assignment(
    session: AsyncSession,
    *,
    profile_id: UUID,
    application_id: UUID,
) -> ProfileRole:
    """Grant the creator app_admin without committing the caller's transaction."""

    assignment = ProfileRole(
        id=creator_app_admin_assignment_id(application_id),
        profile_id=profile_id,
        role_id=APP_ADMIN_ROLE_ID,
        role_scope_kind="application",
        application_id=application_id,
        granted_by_profile_id=profile_id,
    )
    session.add(assignment)
    await session.flush()
    return assignment


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


async def get_application_by_id(
    session: AsyncSession,
    *,
    application_id: UUID,
) -> MonitoredService | None:
    """Return an application by globally unique ID after separate authorization."""

    return await session.get(MonitoredService, application_id)


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


def application_permission_exists(
    *,
    profile_id: UUID,
    application_id: UUID | ColumnElement[UUID] | InstrumentedAttribute[UUID],
    permission_name: str,
) -> ColumnElement[bool]:
    """Build the database-backed global-or-application permission predicate."""

    return exists(
        select(1)
        .select_from(ProfileRole)
        .join(Role, Role.id == ProfileRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            ProfileRole.profile_id == profile_id,
            Permission.name == permission_name,
            or_(
                and_(
                    Role.scope_kind == "global",
                    ProfileRole.application_id.is_(None),
                ),
                and_(
                    Role.scope_kind == "application",
                    ProfileRole.application_id == application_id,
                ),
            ),
        )
    )


async def has_application_permission(
    session: AsyncSession,
    *,
    profile_id: UUID,
    application_id: UUID,
    permission_name: str,
) -> bool:
    """Return whether PostgreSQL grants a permission on one application."""

    granted = await session.scalar(
        select(
            application_permission_exists(
                profile_id=profile_id,
                application_id=application_id,
                permission_name=permission_name,
            )
        )
    )
    return bool(granted)


async def list_authorized_monitored_services(
    session: AsyncSession,
    *,
    profile_id: UUID,
    permission_name: str,
) -> list[MonitoredService]:
    """List exactly the applications on which PostgreSQL grants a permission."""

    result = await session.scalars(
        select(MonitoredService)
        .where(
            application_permission_exists(
                profile_id=profile_id,
                application_id=MonitoredService.id,
                permission_name=permission_name,
            )
        )
        .order_by(MonitoredService.created_at, MonitoredService.id)
    )
    return list(result.all())


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
