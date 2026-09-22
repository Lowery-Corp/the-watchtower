"""Deterministic PostgreSQL races between profile uptime reads and key rotation."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from watchtower.core.api_keys import digest_profile_api_key, parse_profile_api_key
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


async def _backend_pid(connection: AsyncConnection) -> int:
    backend_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
    assert isinstance(backend_pid, int)
    await connection.rollback()
    return backend_pid


async def _wait_for_expected_blocker(
    factory: async_sessionmaker[AsyncSession],
    *,
    blocked_pid: int,
    blocker_pid: int | None,
) -> tuple[int, ...]:
    async with asyncio.timeout(5):
        while True:
            async with factory() as observer:
                activity = (
                    await observer.execute(
                        text(
                            """
                            SELECT
                                activity.state,
                                activity.wait_event_type,
                                activity.wait_event,
                                pg_blocking_pids(:blocked_pid) AS blocker_pids,
                                CASE
                                    WHEN CAST(:blocker_pid AS INTEGER) IS NULL
                                    THEN cardinality(pg_blocking_pids(:blocked_pid)) > 0
                                    ELSE CAST(:blocker_pid AS INTEGER)
                                        = ANY(pg_blocking_pids(:blocked_pid))
                                END AS blocked_by_expected,
                                EXISTS (
                                    SELECT 1
                                    FROM pg_locks AS waiting_lock
                                    WHERE waiting_lock.pid = :blocked_pid
                                      AND NOT waiting_lock.granted
                                ) AS has_ungranted_lock
                            FROM pg_stat_activity AS activity
                            WHERE activity.pid = :blocked_pid
                              AND activity.datname = current_database()
                            """
                        ),
                        {"blocked_pid": blocked_pid, "blocker_pid": blocker_pid},
                    )
                ).one_or_none()
            if (
                activity is not None
                and activity.blocked_by_expected
                and activity.has_ungranted_lock
            ):
                assert activity.state == "active"
                assert activity.wait_event_type == "Lock"
                assert activity.wait_event is not None
                return tuple(activity.blocker_pids)
            await asyncio.sleep(0)


@asynccontextmanager
async def profile_fixture(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[UUID]:
    profile_id = uuid4()
    auth_user_id = uuid4()
    async with factory() as session:
        async with session.begin():
            session.add(Profile(id=profile_id, auth_user_id=auth_user_id))
    try:
        yield profile_id
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(delete(ApiKey).where(ApiKey.profile_id == profile_id))
        async with factory() as session:
            async with session.begin():
                await session.execute(delete(Profile).where(Profile.id == profile_id))


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
    read_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    reissue_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    original_lock_profile = uptime_service._lock_profile

    try:
        async with profile_key_fixture(factory) as (profile_id, _, old_token):
            tasks: list[asyncio.Task[object]] = []
            try:
                async def pause_read_after_profile_lock(
                    session: AsyncSession, locked_profile_id: UUID
                ) -> Profile | None:
                    profile = await original_lock_profile(session, locked_profile_id)
                    read_holds_profile.set()
                    await allow_read_to_finish.wait()
                    return profile

                monkeypatch.setattr(uptime_service, "_lock_profile", pause_read_after_profile_lock)

                old_parsed = parse_profile_api_key(old_token.get_secret_value())

                async def read() -> ProfileUptimeResponse | ProfileUptimeRateLimited:
                    async with engine.connect() as connection:
                        read_pid.set_result(await _backend_pid(connection))
                        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                            return await uptime_service.read_profile_uptime(
                                session,
                                token=old_token.get_secret_value(),
                                public_prefix=old_parsed.public_prefix,
                                max_requests=60,
                                window_seconds=60,
                            )

                async def reissue() -> tuple[ApiKey, SecretStr, bool]:
                    async with engine.connect() as connection:
                        reissue_pid.set_result(await _backend_pid(connection))
                        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                            return await api_key_service.issue_profile_uptime_key(
                                session, profile_id=profile_id
                            )

                read_task = asyncio.create_task(read())
                tasks.append(read_task)
                await asyncio.wait_for(read_holds_profile.wait(), timeout=5)
                reissue_task = asyncio.create_task(reissue())
                tasks.append(reissue_task)
                await _wait_for_expected_blocker(
                    factory,
                    blocked_pid=await asyncio.wait_for(reissue_pid, timeout=5),
                    blocker_pid=await asyncio.wait_for(read_pid, timeout=5),
                )
                allow_read_to_finish.set()
                read_result = await asyncio.wait_for(read_task, timeout=5)
                _, replacement, created = await asyncio.wait_for(reissue_task, timeout=5)

                assert not created
                assert isinstance(read_result, ProfileUptimeResponse)
                assert read_result.profile.id == profile_id
                assert replacement.get_secret_value() != old_token.get_secret_value()
            finally:
                allow_read_to_finish.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_simultaneous_first_profile_key_issue_creates_then_reissues_single_row() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    first_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    second_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with profile_fixture(factory) as profile_id:
            tasks: list[asyncio.Task[tuple[ApiKey, SecretStr, bool]]] = []
            observer_tasks: list[asyncio.Task[tuple[int, ...]]] = []
            try:
                async with engine.connect() as lock_connection:
                    locker_pid = await _backend_pid(lock_connection)
                    locked_profile = await lock_connection.scalar(
                        select(Profile).where(Profile.id == profile_id).with_for_update()
                    )
                    assert locked_profile is not None

                    async def issue(pid: asyncio.Future[int]) -> tuple[ApiKey, SecretStr, bool]:
                        async with engine.connect() as connection:
                            pid.set_result(await _backend_pid(connection))
                            async with AsyncSession(
                                bind=connection, expire_on_commit=False
                            ) as session:
                                return await api_key_service.issue_profile_uptime_key(
                                    session, profile_id=profile_id
                                )

                    tasks = [
                        asyncio.create_task(issue(first_pid)),
                        asyncio.create_task(issue(second_pid)),
                    ]
                    issue_pids = await asyncio.gather(
                        asyncio.wait_for(first_pid, timeout=5),
                        asyncio.wait_for(second_pid, timeout=5),
                    )
                    observer_tasks = [
                        asyncio.create_task(
                            _wait_for_expected_blocker(
                                factory, blocked_pid=pid, blocker_pid=None
                            )
                        )
                        for pid in issue_pids
                    ]
                    blocking_chains = await asyncio.gather(*observer_tasks)
                    assert locker_pid in {pid for chain in blocking_chains for pid in chain}
                    await lock_connection.commit()

                    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

                created_result = next(result for result in results if result[2])
                reissued_result = next(result for result in results if not result[2])
                created_key, superseded_token, _ = created_result
                reissued_key, latest_token, _ = reissued_result
                superseded_value = superseded_token.get_secret_value()
                latest_value = latest_token.get_secret_value()

                async with factory() as session:
                    persisted = list(
                        await session.scalars(
                            select(ApiKey).where(
                                ApiKey.profile_id == profile_id,
                                ApiKey.credential_kind == "profile_uptime",
                            )
                        )
                    )

                assert sorted(result[2] for result in results) == [False, True]
                assert created_key.id == reissued_key.id
                assert superseded_value != latest_value
                assert len(persisted) == 1
                assert persisted[0].id == reissued_key.id
                assert persisted[0].secret_digest != digest_profile_api_key(superseded_value)
                assert persisted[0].secret_digest == digest_profile_api_key(latest_value)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                for observer_task in observer_tasks:
                    if not observer_task.done():
                        observer_task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if observer_tasks:
                    await asyncio.gather(*observer_tasks, return_exceptions=True)
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
            tasks: list[asyncio.Task[object]] = []
            try:
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
                tasks.append(reissue_task)
                await asyncio.wait_for(reissue_holds_key.wait(), timeout=5)
                read_task = asyncio.create_task(read())
                tasks.append(read_task)
                await asyncio.wait_for(read_reached_profile_lock.wait(), timeout=5)
                allow_reissue_to_finish.set()
                await asyncio.wait_for(reissue_task, timeout=5)
                denial = await asyncio.wait_for(read_task, timeout=5)

                assert isinstance(denial, ProfileUptimeAuthenticationError)
            finally:
                allow_reissue_to_finish.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await engine.dispose()
