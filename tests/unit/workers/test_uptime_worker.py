"""Unit coverage for uptime worker lifecycle."""

import asyncio

from watchtower.workers.uptime import wait_for_cycle_or_stop


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
