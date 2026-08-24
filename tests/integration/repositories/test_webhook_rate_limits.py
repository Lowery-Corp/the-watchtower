"""PostgreSQL integration tests for shared webhook request budgets."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.webhook_rate_limit import WebhookRateLimit
from watchtower.repositories.webhook_rate_limits import consume_webhook_rate_limit

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


async def _consume_once(
    factory: async_sessionmaker[AsyncSession],
    *,
    identity: str,
    max_requests: int,
    window_seconds: int,
) -> int | None:
    async with factory() as session:
        async with session.begin():
            return await consume_webhook_rate_limit(
                session,
                identity=identity,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )


@pytest.mark.integration
async def test_concurrent_sessions_share_one_atomic_saturated_budget() -> None:
    identity = f"managed:{uuid4()}"
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    start = asyncio.Event()

    async def synchronized_consume() -> int | None:
        await start.wait()
        return await _consume_once(
            factory,
            identity=identity,
            max_requests=3,
            window_seconds=60,
        )

    try:
        tasks = [asyncio.create_task(synchronized_consume()) for _ in range(10)]
        await asyncio.sleep(0)
        start.set()
        results = await asyncio.gather(*tasks)

        async with factory() as inspection_session:
            row = await inspection_session.scalar(
                select(WebhookRateLimit).where(WebhookRateLimit.identity == identity)
            )

        assert results.count(None) == 3
        assert len([retry for retry in results if retry is not None]) == 7
        assert all(retry is None or 1 <= retry <= 60 for retry in results)
        assert row is not None
        assert row.request_count == 4
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebhookRateLimit).where(WebhookRateLimit.identity == identity)
                )
        await engine.dispose()


@pytest.mark.integration
async def test_rollover_samples_database_time_after_identity_lock_wait() -> None:
    identity = f"managed:{uuid4()}"
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        assert (
            await _consume_once(
                factory,
                identity=identity,
                max_requests=1,
                window_seconds=1,
            )
            is None
        )

        async with factory() as blocker:
            await blocker.begin()
            await blocker.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": identity},
            )
            contender = asyncio.create_task(
                _consume_once(
                    factory,
                    identity=identity,
                    max_requests=1,
                    window_seconds=1,
                )
            )
            await asyncio.sleep(0.1)
            assert not contender.done()
            await asyncio.sleep(1.05)
            await blocker.commit()

        assert await asyncio.wait_for(contender, timeout=5) is None
        async with factory() as inspection_session:
            request_count = await inspection_session.scalar(
                select(WebhookRateLimit.request_count).where(WebhookRateLimit.identity == identity)
            )
        assert request_count == 1
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebhookRateLimit).where(WebhookRateLimit.identity == identity)
                )
        await engine.dispose()


@pytest.mark.integration
async def test_expired_window_resets_and_identities_remain_isolated() -> None:
    first_identity = f"managed:{uuid4()}"
    second_identity = f"legacy:{uuid4()}:service-{uuid4().hex}"
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    identities = [first_identity, second_identity]

    try:
        assert (
            await _consume_once(
                factory,
                identity=first_identity,
                max_requests=1,
                window_seconds=60,
            )
            is None
        )
        limited = await _consume_once(
            factory,
            identity=first_identity,
            max_requests=1,
            window_seconds=60,
        )
        assert limited is not None
        assert 1 <= limited <= 60
        assert (
            await _consume_once(
                factory,
                identity=second_identity,
                max_requests=1,
                window_seconds=60,
            )
            is None
        )

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(WebhookRateLimit)
                    .where(WebhookRateLimit.identity == first_identity)
                    .values(
                        window_started_at=func.statement_timestamp() - text("interval '61 seconds'")
                    )
                )

        assert (
            await _consume_once(
                factory,
                identity=first_identity,
                max_requests=1,
                window_seconds=60,
            )
            is None
        )
        async with factory() as inspection_session:
            rows = (
                await inspection_session.execute(
                    select(
                        WebhookRateLimit.identity,
                        WebhookRateLimit.request_count,
                    ).where(WebhookRateLimit.identity.in_(identities))
                )
            ).tuples()
            counts: dict[str, int] = {identity: request_count for identity, request_count in rows}
        assert counts == {first_identity: 1, second_identity: 1}
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebhookRateLimit).where(WebhookRateLimit.identity.in_(identities))
                )
        await engine.dispose()


@pytest.mark.integration
async def test_consumption_prunes_stale_inactive_identity_rows() -> None:
    stale_identity = f"managed:{uuid4()}"
    active_identity = f"managed:{uuid4()}"
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    identities = [stale_identity, active_identity]

    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    WebhookRateLimit(
                        identity=stale_identity,
                        window_started_at=datetime.now(UTC) - timedelta(days=2),
                        request_count=1,
                    )
                )

        assert (
            await _consume_once(
                factory,
                identity=active_identity,
                max_requests=1,
                window_seconds=60,
            )
            is None
        )
        async with factory() as inspection_session:
            remaining = set(
                (
                    await inspection_session.scalars(
                        select(WebhookRateLimit.identity).where(
                            WebhookRateLimit.identity.in_(identities)
                        )
                    )
                ).all()
            )
        assert remaining == {active_identity}
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebhookRateLimit).where(WebhookRateLimit.identity.in_(identities))
                )
        await engine.dispose()


@pytest.mark.integration
async def test_pruning_serializes_reactivation_before_sampling_window_time() -> None:
    stale_identity = f"managed:{uuid4()}"
    trigger_identity = f"managed:{uuid4()}"
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    identities = [stale_identity, trigger_identity]
    blocker: AsyncSession | None = None

    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    WebhookRateLimit(
                        identity=stale_identity,
                        window_started_at=datetime.now(UTC) - timedelta(days=2),
                        request_count=1,
                    )
                )

        blocker = factory()
        await blocker.begin()
        assert (
            await consume_webhook_rate_limit(
                blocker,
                identity=trigger_identity,
                max_requests=1,
                window_seconds=2,
            )
            is None
        )
        assert (
            await blocker.scalar(
                select(func.count())
                .select_from(WebhookRateLimit)
                .where(WebhookRateLimit.identity == stale_identity)
            )
            == 0
        )

        contender = asyncio.create_task(
            _consume_once(
                factory,
                identity=stale_identity,
                max_requests=1,
                window_seconds=2,
            )
        )
        await asyncio.sleep(0.1)
        assert not contender.done()
        await asyncio.sleep(2.05)
        release_floor = await blocker.scalar(select(func.clock_timestamp()))
        assert release_floor is not None
        await blocker.commit()

        assert await asyncio.wait_for(contender, timeout=5) is None
        async with factory() as inspection_session:
            window_started_at = await inspection_session.scalar(
                select(WebhookRateLimit.window_started_at).where(
                    WebhookRateLimit.identity == stale_identity
                )
            )
        assert window_started_at is not None
        assert window_started_at >= release_floor
    finally:
        if blocker is not None:
            if blocker.in_transaction():
                await blocker.rollback()
            await blocker.close()
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebhookRateLimit).where(WebhookRateLimit.identity.in_(identities))
                )
        await engine.dispose()
