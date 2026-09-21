"""PostgreSQL integration tests for application authorization queries."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import (
    APP_ADMIN_ROLE_ID,
    VIEWER_ROLE_ID,
    WATCHTOWER_ADMIN_ROLE_ID,
)
from watchtower.repositories.monitored_services import (
    has_application_permission,
    list_authorized_monitored_services,
)

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


@pytest.mark.integration
async def test_database_roles_enforce_global_and_application_permission_scopes() -> None:
    owner, app_admin, viewer, unrelated, global_admin = [
        Profile(id=uuid4(), auth_user_id=uuid4(), display_name=name)
        for name in ("Owner", "App admin", "Viewer", "Unrelated", "Global admin")
    ]
    first = MonitoredService(
        profile_id=owner.id,
        slug=f"first-{uuid4().hex}",
        display_name="First",
        environment="test",
        secret_key_id="managed",
    )
    second = MonitoredService(
        profile_id=unrelated.id,
        slug=f"second-{uuid4().hex}",
        display_name="Second",
        environment="test",
        secret_key_id="managed",
    )
    profiles = [owner, app_admin, viewer, unrelated, global_admin]
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(profiles)
                await session.flush()
                session.add_all([first, second])
                await session.flush()
                session.add_all(
                    [
                        ProfileRole(
                            profile_id=app_admin.id,
                            role_id=APP_ADMIN_ROLE_ID,
                            role_scope_kind="application",
                            application_id=first.id,
                            granted_by_profile_id=owner.id,
                        ),
                        ProfileRole(
                            profile_id=viewer.id,
                            role_id=VIEWER_ROLE_ID,
                            role_scope_kind="application",
                            application_id=first.id,
                            granted_by_profile_id=owner.id,
                        ),
                        ProfileRole(
                            profile_id=global_admin.id,
                            role_id=WATCHTOWER_ADMIN_ROLE_ID,
                            role_scope_kind="global",
                            granted_by_profile_id=global_admin.id,
                        ),
                    ]
                )

        async with factory() as session:
            assert await has_application_permission(
                session,
                profile_id=app_admin.id,
                application_id=first.id,
                permission_name="applications.read",
            )
            assert await has_application_permission(
                session,
                profile_id=app_admin.id,
                application_id=first.id,
                permission_name="applications.manage",
            )
            assert await has_application_permission(
                session,
                profile_id=viewer.id,
                application_id=first.id,
                permission_name="applications.read",
            )
            assert not await has_application_permission(
                session,
                profile_id=viewer.id,
                application_id=first.id,
                permission_name="applications.manage",
            )
            assert not await has_application_permission(
                session,
                profile_id=app_admin.id,
                application_id=second.id,
                permission_name="applications.read",
            )
            assert not await has_application_permission(
                session,
                profile_id=unrelated.id,
                application_id=first.id,
                permission_name="applications.read",
            )
            assert await has_application_permission(
                session,
                profile_id=global_admin.id,
                application_id=first.id,
                permission_name="applications.manage",
            )
            assert await has_application_permission(
                session,
                profile_id=global_admin.id,
                application_id=second.id,
                permission_name="applications.read",
            )
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ProfileRole).where(
                        ProfileRole.profile_id.in_([profile.id for profile in profiles])
                    )
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id.in_([first.id, second.id]))
                )
                await session.execute(
                    delete(Profile).where(Profile.id.in_([profile.id for profile in profiles]))
                )
        await engine.dispose()


@pytest.mark.integration
async def test_authorized_list_returns_exactly_readable_applications() -> None:
    owner, member, global_admin = [
        Profile(id=uuid4(), auth_user_id=uuid4(), display_name=name)
        for name in ("Owner", "Member", "Global admin")
    ]
    services = [
        MonitoredService(
            profile_id=owner.id,
            slug=f"visible-{uuid4().hex}",
            display_name=f"Service {index}",
            environment="test",
            secret_key_id="managed",
        )
        for index in range(3)
    ]
    profiles = [owner, member, global_admin]
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(profiles)
                await session.flush()
                session.add_all(services)
                await session.flush()
                session.add_all(
                    [
                        ProfileRole(
                            profile_id=member.id,
                            role_id=VIEWER_ROLE_ID,
                            role_scope_kind="application",
                            application_id=service.id,
                            granted_by_profile_id=owner.id,
                        )
                        for service in (services[0], services[2])
                    ]
                    + [
                        ProfileRole(
                            profile_id=global_admin.id,
                            role_id=WATCHTOWER_ADMIN_ROLE_ID,
                            role_scope_kind="global",
                            granted_by_profile_id=global_admin.id,
                        )
                    ]
                )

        async with factory() as session:
            member_services = await list_authorized_monitored_services(
                session,
                profile_id=member.id,
                permission_name="applications.read",
            )
            admin_services = await list_authorized_monitored_services(
                session,
                profile_id=global_admin.id,
                permission_name="applications.read",
            )

        assert {service.id for service in member_services} == {services[0].id, services[2].id}
        assert {service.id for service in admin_services} >= {service.id for service in services}
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ProfileRole).where(
                        ProfileRole.profile_id.in_([profile.id for profile in profiles])
                    )
                )
                await session.execute(
                    delete(MonitoredService).where(
                        MonitoredService.id.in_([service.id for service in services])
                    )
                )
                await session.execute(
                    delete(Profile).where(Profile.id.in_([profile.id for profile in profiles]))
                )
        await engine.dispose()
