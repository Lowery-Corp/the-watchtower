"""PostgreSQL integration coverage for durable Watchtower role assignments."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import (
    APP_ADMIN_ROLE_ID,
    VIEWER_ROLE_ID,
    WATCHTOWER_ADMIN_ROLE_ID,
    Role,
)

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)
OWNER_PROFILE_ID = UUID("133ae893-cbf4-57a6-89a5-0a95107050d7")
OWNER_SERVICE_ID = UUID("47018848-834d-5d91-8a39-bbe8b6fa32b1")
OWNER_ASSIGNMENT_ID = UUID("3bd10160-c26b-1f40-637e-dd7d32d7534a")


async def _run_alembic(database_url: str, *arguments: str) -> None:
    environment = {**os.environ, "WATCHTOWER_DATABASE_URL": database_url}
    process = await asyncio.create_subprocess_exec(
        "alembic",
        *arguments,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    assert process.returncode == 0, output.decode()


@pytest_asyncio.fixture(scope="module")
async def role_database_url() -> AsyncIterator[str]:
    """Build the role migration on a disposable database, never the configured database."""

    source_url = make_url(DATABASE_URL)
    database_name = f"watchtower_roles_{uuid4().hex}"
    admin_url = source_url.set(database="postgres")
    role_url = source_url.set(database=database_name)
    admin_engine = create_async_engine(
        admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )

    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    rendered_role_url = role_url.render_as_string(hide_password=False)
    try:
        await _run_alembic(rendered_role_url, "upgrade", "0012_profile_auth_metadata")
        engine = create_async_database_engine(rendered_role_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO watchtower.profile "
                        "(id, auth_user_id, display_name) VALUES (:id, :auth_user_id, 'Owner')"
                    ),
                    {"id": OWNER_PROFILE_ID, "auth_user_id": uuid4()},
                )
                await connection.execute(
                    text(
                        "INSERT INTO watchtower.monitored_service "
                        "(id, profile_id, slug, display_name, environment, active, secret_key_id) "
                        "VALUES (:id, :profile_id, 'preexisting', 'Preexisting', "
                        "'test', true, 'legacy')"
                    ),
                    {"id": OWNER_SERVICE_ID, "profile_id": OWNER_PROFILE_ID},
                )
        finally:
            await engine.dispose()
        await _run_alembic(rendered_role_url, "upgrade", "head")
        yield rendered_role_url
    finally:
        cleanup_engine = create_async_engine(
            admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
        )
        try:
            async with cleanup_engine.connect() as connection:
                await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        finally:
            await cleanup_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.integration
async def test_migration_seeds_stable_scoped_roles_and_backfills_owner(
    role_database_url: str,
) -> None:
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)

    try:
        async with factory() as session:
            roles = list(
                (
                    await session.execute(
                        select(Role.id, Role.name, Role.scope_kind).order_by(Role.name)
                    )
                ).tuples()
            )
            assignments = (
                (
                    await session.execute(
                        select(ProfileRole).where(ProfileRole.application_id == OWNER_SERVICE_ID)
                    )
                )
                .scalars()
                .all()
            )
            indexes = set(
                await session.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'watchtower' AND tablename = 'profile_role'"
                    )
                )
            )

        assert roles == [
            (APP_ADMIN_ROLE_ID, "app_admin", "application"),
            (VIEWER_ROLE_ID, "viewer", "application"),
            (WATCHTOWER_ADMIN_ROLE_ID, "watchtower_admin", "global"),
        ]
        assert len(assignments) == 1
        assert assignments[0].id == OWNER_ASSIGNMENT_ID
        assert assignments[0].profile_id == OWNER_PROFILE_ID
        assert assignments[0].role_id == APP_ADMIN_ROLE_ID
        assert assignments[0].role_scope_kind == "application"
        assert assignments[0].granted_by_profile_id is None
        assert {
            "ix_profile_role_role_scope",
            "ix_profile_role_granted_by_profile",
        } <= indexes
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_role_names_and_declared_scopes_are_database_constrained(
    role_database_url: str,
) -> None:
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)

    try:
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(Role(id=uuid4(), name="viewer", scope_kind="application"))
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(Role(id=uuid4(), name="watchtower_admin", scope_kind="application"))
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_duplicate_global_and_application_assignments_are_rejected(
    role_database_url: str,
) -> None:
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)
    profile = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Duplicate test")
    service = MonitoredService(
        profile_id=profile.id,
        slug=f"duplicates-{uuid4().hex}",
        display_name="Duplicates",
        environment="test",
        active=True,
        secret_key_id="legacy",
    )

    try:
        async with factory() as session:
            async with session.begin():
                session.add(profile)
                await session.flush()
                session.add(service)
                await session.flush()
                session.add_all(
                    [
                        ProfileRole(
                            profile_id=profile.id,
                            role_id=WATCHTOWER_ADMIN_ROLE_ID,
                            role_scope_kind="global",
                        ),
                        ProfileRole(
                            profile_id=profile.id,
                            role_id=APP_ADMIN_ROLE_ID,
                            role_scope_kind="application",
                            application_id=service.id,
                        ),
                    ]
                )
        for duplicate in (
            ProfileRole(
                profile_id=profile.id,
                role_id=WATCHTOWER_ADMIN_ROLE_ID,
                role_scope_kind="global",
            ),
            ProfileRole(
                profile_id=profile.id,
                role_id=APP_ADMIN_ROLE_ID,
                role_scope_kind="application",
                application_id=service.id,
            ),
        ):
            async with factory() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        session.add(duplicate)
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ProfileRole).where(ProfileRole.profile_id == profile.id)
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service.id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile.id))
        await engine.dispose()


@pytest.mark.integration
async def test_role_scope_cannot_drift_from_assignment_scope(role_database_url: str) -> None:
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)
    profile = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Scope test")
    service = MonitoredService(
        profile_id=profile.id,
        slug=f"scope-{uuid4().hex}",
        display_name="Scope",
        environment="test",
        active=True,
        secret_key_id="legacy",
    )

    try:
        async with factory() as session:
            async with session.begin():
                session.add(profile)
                await session.flush()
                session.add(service)
        invalid_assignments = (
            ProfileRole(
                profile_id=profile.id,
                role_id=APP_ADMIN_ROLE_ID,
                role_scope_kind="application",
            ),
            ProfileRole(
                profile_id=profile.id,
                role_id=WATCHTOWER_ADMIN_ROLE_ID,
                role_scope_kind="global",
                application_id=service.id,
            ),
            ProfileRole(
                profile_id=profile.id,
                role_id=APP_ADMIN_ROLE_ID,
                role_scope_kind="global",
            ),
        )
        for assignment in invalid_assignments:
            async with factory() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        session.add(assignment)
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service.id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile.id))
        await engine.dispose()


@pytest.mark.integration
async def test_assignment_foreign_keys_and_security_deletes_are_restrictive(
    role_database_url: str,
) -> None:
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)
    profile = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Member")
    grantor = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Grantor")
    service = MonitoredService(
        profile_id=profile.id,
        slug=f"restrict-{uuid4().hex}",
        display_name="Restrict",
        environment="test",
        active=True,
        secret_key_id="legacy",
    )

    try:
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        ProfileRole(
                            profile_id=uuid4(),
                            role_id=WATCHTOWER_ADMIN_ROLE_ID,
                            role_scope_kind="global",
                        )
                    )
        async with factory() as session:
            async with session.begin():
                session.add_all([profile, grantor])
                await session.flush()
                session.add(service)
                await session.flush()
                session.add(
                    ProfileRole(
                        profile_id=profile.id,
                        role_id=VIEWER_ROLE_ID,
                        role_scope_kind="application",
                        application_id=service.id,
                        granted_by_profile_id=grantor.id,
                    )
                )
        for statement in (
            delete(Profile).where(Profile.id == profile.id),
            delete(Profile).where(Profile.id == grantor.id),
            delete(MonitoredService).where(MonitoredService.id == service.id),
            delete(Role).where(Role.id == VIEWER_ROLE_ID),
        ):
            async with factory() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        await session.execute(statement)
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ProfileRole).where(ProfileRole.profile_id == profile.id)
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service.id)
                )
                await session.execute(
                    delete(Profile).where(Profile.id.in_([profile.id, grantor.id]))
                )
        await engine.dispose()


@pytest.mark.integration
async def test_memberships_are_isolated_by_profile_and_application(role_database_url: str) -> None:
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)
    profiles = [Profile(id=uuid4(), auth_user_id=uuid4(), display_name=name) for name in ("A", "B")]
    services = [
        MonitoredService(
            profile_id=profile.id,
            slug=f"isolation-{uuid4().hex}",
            display_name=f"Service {profile.display_name}",
            environment="test",
            active=True,
            secret_key_id="legacy",
        )
        for profile in profiles
    ]

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
                            profile_id=profile.id,
                            role_id=VIEWER_ROLE_ID,
                            role_scope_kind="application",
                            application_id=service.id,
                        )
                        for profile, service in zip(profiles, services, strict=True)
                    ]
                )
        async with factory() as session:
            profile_a_apps = set(
                await session.scalars(
                    select(ProfileRole.application_id).where(
                        ProfileRole.profile_id == profiles[0].id
                    )
                )
            )
            service_b_members = set(
                await session.scalars(
                    select(ProfileRole.profile_id).where(
                        ProfileRole.application_id == services[1].id
                    )
                )
            )
        assert profile_a_apps == {services[0].id}
        assert service_b_members == {profiles[1].id}
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ProfileRole).where(ProfileRole.profile_id.in_([p.id for p in profiles]))
                )
                await session.execute(
                    delete(MonitoredService).where(
                        MonitoredService.id.in_([service.id for service in services])
                    )
                )
                await session.execute(
                    delete(Profile).where(Profile.id.in_([p.id for p in profiles]))
                )
        await engine.dispose()


@pytest.mark.integration
async def test_downgrade_removes_only_role_feature_and_reupgrade_backfills_once(
    role_database_url: str,
) -> None:
    await _run_alembic(role_database_url, "downgrade", "0012_profile_auth_metadata")
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)
    try:
        async with factory() as session:
            tables = set(
                await session.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'watchtower'"
                    )
                )
            )
        assert "profile" in tables
        assert "monitored_service" in tables
        assert "role" not in tables
        assert "profile_role" not in tables
    finally:
        await engine.dispose()

    await _run_alembic(role_database_url, "upgrade", "head")
    engine = create_async_database_engine(role_database_url)
    factory = create_session_factory(role_database_url, engine=engine)
    try:
        async with factory() as session:
            count = await session.scalar(
                select(func.count(ProfileRole.id)).where(
                    ProfileRole.profile_id == OWNER_PROFILE_ID,
                    ProfileRole.role_id == APP_ADMIN_ROLE_ID,
                    ProfileRole.application_id == OWNER_SERVICE_ID,
                )
            )
        assert count == 1
    finally:
        await engine.dispose()
