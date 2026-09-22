"""Deterministic PostgreSQL races between profile uptime reads and key rotation."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchtower.core.api_keys import GeneratedApiKey, parse_profile_api_key
from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.api_key import ApiKey
from watchtower.models.profile import Profile
from watchtower.models.webhook_rate_limit import WebhookRateLimit
from watchtower.schemas.profile_uptime import ProfileUptimeResponse
from watchtower.services import api_keys as api_key_service
from watchtower.services import profile_uptime as uptime_service
from watchtower.services.profile_uptime import (
    ProfileUptimeAuthenticationError,
    ProfileUptimeRateLimited,
)

DATABASE_URL = os.environ["WATCHTOWER_DATABASE_URL"]


@asynccontextmanager
async def profile_key_fixture(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID, SecretStr]]:
    profile_id = uuid4()
    auth_user_id = uuid4()
    async with factory() as session:
        async with session.begin():
            session.add(Profile(id=profile_id, auth_user_id=auth_user_id))
    async with factory() as session:
        key, token, created = await api_key_service.issue_profile_uptime_key(
            session, profile_id=profile_id
        )
    assert created
    try:
        yield profile_id, key.id, token
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebhookRateLimit).where(
                        WebhookRateLimit.identity == f"profile-uptime:{key.id}"
                    )
                )
                await session.execute(delete(ApiKey).where(ApiKey.id == key.id))
                await session.execute(delete(Profile).where(Profile.id == profile_id))


@pytest.mark.integration
async def test_read_holding_profile_lock_linearizes_before_reissue(
    monkeypatch: MonkeyPatch,
) -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    read_holds_profile = asyncio.Event()
    allow_read_to_finish = asyncio.Event()
    reissue_started = asyncio.Event()
    original_lock_profile = uptime_service._lock_profile
    original_generate = api_key_service.generate_profile_api_key  # type: ignore[attr-defined]

    try:
        async with profile_key_fixture(factory) as (profile_id, _, old_token):
            async def pause_read_after_profile_lock(
                session: AsyncSession, locked_profile_id: UUID
            ) -> Profile | None:
                profile = await original_lock_profile(session, locked_profile_id)
                read_holds_profile.set()
                await allow_read_to_finish.wait()
                return profile

            def observe_reissue_start() -> GeneratedApiKey:
                reissue_started.set()
                return original_generate()

            monkeypatch.setattr(uptime_service, "_lock_profile", pause_read_after_profile_lock)
            monkeypatch.setattr(
                api_key_service, "generate_profile_api_key", observe_reissue_start
            )

            old_parsed = parse_profile_api_key(old_token.get_secret_value())

            async def read() -> ProfileUptimeResponse | ProfileUptimeRateLimited:
                async with factory() as session:
                    return await uptime_service.read_profile_uptime(
                        session,
                        token=old_token.get_secret_value(),
                        public_prefix=old_parsed.public_prefix,
                        max_requests=60,
                        window_seconds=60,
                    )

            async def reissue() -> tuple[ApiKey, SecretStr, bool]:
                async with factory() as session:
                    return await api_key_service.issue_profile_uptime_key(
                        session, profile_id=profile_id
                    )

            read_task = asyncio.create_task(read())
            await asyncio.wait_for(read_holds_profile.wait(), timeout=5)
            reissue_task = asyncio.create_task(reissue())
            await asyncio.wait_for(reissue_started.wait(), timeout=5)
            allow_read_to_finish.set()
            read_result = await asyncio.wait_for(read_task, timeout=5)
            _, replacement, created = await asyncio.wait_for(reissue_task, timeout=5)

            assert not created
            assert isinstance(read_result, ProfileUptimeResponse)
            assert read_result.profile.id == profile_id
            assert replacement.get_secret_value() != old_token.get_secret_value()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_reissue_holding_profile_and_key_locks_invalidates_waiting_read(
    monkeypatch: MonkeyPatch,
) -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    reissue_holds_key = asyncio.Event()
    allow_reissue_to_finish = asyncio.Event()
    read_reached_profile_lock = asyncio.Event()
    original_get_key = api_key_service.get_profile_uptime_key  # type: ignore[attr-defined]
    original_lock_profile = uptime_service._lock_profile

    try:
        async with profile_key_fixture(factory) as (profile_id, _, old_token):
            async def pause_reissue_after_key_lock(
                session: AsyncSession, *, profile_id: UUID, for_update: bool = False
            ) -> ApiKey | None:
                key = await original_get_key(
                    session, profile_id=profile_id, for_update=for_update
                )
                if for_update:
                    reissue_holds_key.set()
                    await allow_reissue_to_finish.wait()
                return key

            async def observe_waiting_read(
                session: AsyncSession, locked_profile_id: UUID
            ) -> Profile | None:
                read_reached_profile_lock.set()
                return await original_lock_profile(session, locked_profile_id)

            monkeypatch.setattr(
                api_key_service, "get_profile_uptime_key", pause_reissue_after_key_lock
            )
            monkeypatch.setattr(uptime_service, "_lock_profile", observe_waiting_read)

            old_parsed = parse_profile_api_key(old_token.get_secret_value())

            async def reissue() -> tuple[ApiKey, SecretStr, bool]:
                async with factory() as session:
                    return await api_key_service.issue_profile_uptime_key(
                        session, profile_id=profile_id
                    )

            async def read() -> ProfileUptimeAuthenticationError | None:
                try:
                    async with factory() as session:
                        await uptime_service.read_profile_uptime(
                            session,
                            token=old_token.get_secret_value(),
                            public_prefix=old_parsed.public_prefix,
                            max_requests=60,
                            window_seconds=60,
                        )
                except ProfileUptimeAuthenticationError as exc:
                    return exc
                return None

            reissue_task = asyncio.create_task(reissue())
            await asyncio.wait_for(reissue_holds_key.wait(), timeout=5)
            read_task = asyncio.create_task(read())
            await asyncio.wait_for(read_reached_profile_lock.wait(), timeout=5)
            allow_reissue_to_finish.set()
            await asyncio.wait_for(reissue_task, timeout=5)
            denial = await asyncio.wait_for(read_task, timeout=5)

            assert isinstance(denial, ProfileUptimeAuthenticationError)
    finally:
        await engine.dispose()
