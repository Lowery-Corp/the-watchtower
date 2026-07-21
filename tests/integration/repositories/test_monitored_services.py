"""PostgreSQL integration tests for profile-owned monitored services."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.repositories.monitored_services import (
    create_monitored_service,
    get_monitored_service_by_slug,
)

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


@pytest.mark.integration
async def test_service_repository_creates_and_finds_active_service() -> None:
    slug = f"service-{uuid4().hex}"
    profile_id = uuid4()
    profile = Profile(
        id=profile_id,
        auth_user_id=uuid4(),
        display_name="Repository owner",
    )
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with factory() as session:
            async with session.begin():
                session.add(profile)
                await session.flush()
                created = await create_monitored_service(
                    session,
                    profile_id=profile_id,
                    slug=slug,
                    display_name="Integration service",
                    environment="test",
                    secret_key_id="primary",
                )

        async with factory() as session:
            found = await get_monitored_service_by_slug(
                session, profile_id=profile_id, slug=slug
            )

        assert found is not None
        assert found.id == created.id
        assert found.profile_id == profile_id
        assert found.active is True
        assert found.secret_key_id == "primary"
        assert "secret" not in MonitoredService.__table__.columns.keys()
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(MonitoredService).where(
                        MonitoredService.profile_id == profile_id
                    )
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()


@pytest.mark.integration
async def test_service_repository_leaves_transaction_ownership_to_caller() -> None:
    slug = f"rollback-{uuid4().hex}"
    profile_id = uuid4()
    profile = Profile(
        id=profile_id,
        auth_user_id=uuid4(),
        display_name="Rollback owner",
    )
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with factory() as session:
            async with session.begin():
                session.add(profile)
                await session.flush()
            await create_monitored_service(
                session,
                profile_id=profile_id,
                slug=slug,
                display_name="Rollback service",
                environment="test",
                secret_key_id="primary",
            )
            await session.rollback()

        async with factory() as session:
            found = await get_monitored_service_by_slug(
                session, profile_id=profile_id, slug=slug
            )

        assert found is None
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(MonitoredService).where(
                        MonitoredService.profile_id == profile_id
                    )
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()


@pytest.mark.integration
async def test_service_slug_is_unique_only_within_profile() -> None:
    slug = f"duplicate-{uuid4().hex}"
    profile_id = uuid4()
    profile = Profile(
        id=profile_id,
        auth_user_id=uuid4(),
        display_name="Duplicate owner",
    )
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with factory() as session:
            session.add(profile)
            await session.flush()
            session.add_all(
                [
                    MonitoredService(
                        profile_id=profile_id,
                        slug=slug,
                        display_name="First",
                        environment="test",
                        secret_key_id="primary",
                    ),
                    MonitoredService(
                        profile_id=profile_id,
                        slug=slug,
                        display_name="Second",
                        environment="test",
                        secret_key_id="primary",
                    ),
                ]
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(MonitoredService).where(
                        MonitoredService.profile_id == profile_id
                    )
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()
