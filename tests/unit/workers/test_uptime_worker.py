"""Unit coverage for uptime worker lifecycle."""

import asyncio

from watchtower.core.config import Settings
from watchtower.workers.uptime import (
    claim_batch_size,
    claim_lease_seconds,
    wait_for_cycle_or_stop,
)


async def test_stop_cancels_active_cycle_promptly() -> None:
    stop = asyncio.Event()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def cycle() -> None:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    task = asyncio.create_task(wait_for_cycle_or_stop(cycle(), stop))
    await started.wait()
    stop.set()

    completed = await asyncio.wait_for(task, timeout=1)

    assert completed is False
    assert cancelled.is_set()


def test_claim_lease_outlasts_probe_timeout() -> None:
    settings = Settings(
        _env_file=None,
        uptime_check_interval_seconds=10,
        uptime_check_timeout_seconds=30,
    )

    assert claim_lease_seconds(settings) == 35


async def test_parent_cancellation_cleans_up_cycle_and_stop_tasks() -> None:
    stop = asyncio.Event()
    cycle_started = asyncio.Event()
    cycle_cancelled = asyncio.Event()

    async def cycle() -> None:
        cycle_started.set()
        try:
            await asyncio.Future()
        finally:
            cycle_cancelled.set()

    parent = asyncio.create_task(wait_for_cycle_or_stop(cycle(), stop))
    await cycle_started.wait()
    parent.cancel()
    try:
        await parent
    except asyncio.CancelledError:
        pass

    await asyncio.sleep(0)
    assert cycle_cancelled.is_set()


def test_claim_batch_never_queues_behind_concurrency() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://watchtower:test@db:5432/watchtower_test",
        auth_service_url="http://auth.test",
        uptime_worker_batch_size=1000,
        uptime_worker_concurrency=1,
        uptime_probe_timeout_seconds=30,
        uptime_check_interval_seconds=10,
    )

    assert claim_batch_size(settings) == 1
