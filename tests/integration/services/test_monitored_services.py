"""PostgreSQL integration tests for monitored-service use cases."""

import hashlib
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import APP_ADMIN_ROLE_ID
from watchtower.schemas.monitored_service import MonitoredServiceCreate
from watchtower.services import monitored_services
from watchtower.services.monitored_services import create_service

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


def creator_assignment_id(application_id: UUID) -> UUID:
    """Mirror the deterministic identifier used by the 0013 owner backfill."""

    digest = hashlib.md5(  # noqa: S324 - deterministic identifier, not security
        f"watchtower-owner-app-admin:{application_id}".encode()
    ).hexdigest()
    return UUID(digest)


@pytest.mark.integration
async def test_create_service_atomically_grants_creator_app_admin() -> None:
    profile = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Creator")
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with factory() as session:
            async with session.begin():
                session.add(profile)
            created = await create_service(
                session,
                profile_id=profile.id,
                payload=MonitoredServiceCreate(
                    slug=f"creator-{uuid4().hex}",
                    display_name="Creator service",
                    environment="test",
                ),
            )

        async with factory() as session:
            assignment = await session.scalar(
                select(ProfileRole).where(ProfileRole.application_id == created.id)
            )

        assert assignment is not None
        assert assignment.id == creator_assignment_id(created.id)
        assert assignment.profile_id == profile.id
        assert assignment.role_id == APP_ADMIN_ROLE_ID
        assert assignment.role_scope_kind == "application"
        assert assignment.granted_by_profile_id == profile.id
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ProfileRole).where(ProfileRole.profile_id == profile.id)
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.profile_id == profile.id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile.id))
        await engine.dispose()


@pytest.mark.integration
async def test_assignment_failure_rolls_back_new_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Rollback creator")
    profile_id = profile.id
    slug = f"assignment-rollback-{uuid4().hex}"
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    async def fail_assignment(*args: object, **kwargs: object) -> ProfileRole:
        raise IntegrityError("forced assignment failure", {}, Exception("forced"))

    monkeypatch.setattr(
        monitored_services,
        "create_creator_app_admin_assignment",
        fail_assignment,
    )

    try:
        async with factory() as session:
            async with session.begin():
                session.add(profile)
            with pytest.raises(IntegrityError):
                await create_service(
                    session,
                    profile_id=profile_id,
                    payload=MonitoredServiceCreate(
                        slug=slug,
                        display_name="Must roll back",
                        environment="test",
                    ),
                )

        async with factory() as session:
            persisted = await session.scalar(
                select(MonitoredService).where(
                    MonitoredService.profile_id == profile_id,
                    MonitoredService.slug == slug,
                )
            )
        assert persisted is None
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ProfileRole).where(ProfileRole.profile_id == profile_id)
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.profile_id == profile_id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()
