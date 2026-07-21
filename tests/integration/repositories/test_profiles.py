"""PostgreSQL integration tests for Watchtower profile provisioning."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.profile import Profile
from watchtower.repositories.profiles import get_or_create_profile

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


@pytest.mark.integration
async def test_concurrent_first_access_creates_exactly_one_profile() -> None:
    auth_user_id = uuid4()
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    async def provision() -> Profile:
        async with factory() as session:
            async with session.begin():
                return await get_or_create_profile(
                    session,
                    auth_user_id=auth_user_id,
                    display_name="Auth User",
                )

    try:
        first, second = await asyncio.gather(provision(), provision())
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Profile).where(Profile.auth_user_id == auth_user_id)
                    )
                ).all()
            )

        assert first.id == second.id
        assert len(rows) == 1
        assert rows[0].display_name == "Auth User"
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(Profile).where(Profile.auth_user_id == auth_user_id)
                )
        await engine.dispose()


@pytest.mark.integration
async def test_profile_repository_leaves_rollback_to_caller() -> None:
    auth_user_id = uuid4()
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with factory() as session:
            await get_or_create_profile(
                session,
                auth_user_id=auth_user_id,
                display_name=None,
            )
            await session.rollback()

        async with factory() as session:
            found = await session.scalar(
                select(Profile).where(Profile.auth_user_id == auth_user_id)
            )

        assert found is None
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(Profile).where(Profile.auth_user_id == auth_user_id)
                )
        await engine.dispose()
