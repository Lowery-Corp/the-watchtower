"""Periodic website uptime worker entry point."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchtower.core.config import Settings
from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.repositories.website_monitors import (
    ClaimedWebsiteMonitor,
    claim_due_website_monitors,
    lock_active_website_monitor,
    prune_website_monitor_checks,
    record_website_monitor_check,
)
from watchtower.uptime.probe import ProbeResult, probe_url

logger = logging.getLogger(__name__)
Probe = Callable[..., Awaitable[ProbeResult]]


def claim_batch_size(settings: Settings) -> int:
    """Claim only work that can begin immediately without semaphore queueing."""

    return min(settings.uptime_worker_batch_size, settings.uptime_worker_concurrency)


def claim_lease_seconds(settings: Settings) -> int:
    """Keep a claim unavailable beyond the longest permitted probe."""

    return max(
        settings.uptime_check_interval_seconds,
        ceil(settings.uptime_check_timeout_seconds) + 5,
    )


async def run_uptime_cycle(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    probe: Probe = probe_url,
    monitor_ids: set[UUID] | None = None,
) -> int:
    """Claim and probe one bounded batch, returning the number claimed."""

    now = datetime.now(UTC)
    async with factory() as session:
        async with session.begin():
            claimed = await claim_due_website_monitors(
                session,
                now=now,
                interval_seconds=claim_lease_seconds(settings),
                limit=claim_batch_size(settings),
                monitor_ids=monitor_ids,
            )

    async def process(item: ClaimedWebsiteMonitor) -> None:
        try:
            async with factory() as session:
                async with session.begin():
                    if not await lock_active_website_monitor(session, monitor_id=item.id):
                        return
                    result = await probe(
                        item.url,
                        timeout_seconds=settings.uptime_check_timeout_seconds,
                    )
                    checked_at = datetime.now(UTC)
                    recorded = await record_website_monitor_check(
                        session,
                        monitor_id=item.id,
                        checked_at=checked_at,
                        result=result,
                        next_check_at=checked_at
                        + timedelta(seconds=settings.uptime_check_interval_seconds),
                    )
            if not recorded:
                return
            logger.info(
                "uptime check completed",
                extra={
                    "monitor_id": str(item.id),
                    "is_up": result.is_up,
                    "failure_kind": result.failure_kind,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "uptime check failed unexpectedly",
                extra={"monitor_id": str(item.id)},
            )
            try:
                async with factory() as session:
                    async with session.begin():
                        await record_website_monitor_check(
                            session,
                            monitor_id=item.id,
                            checked_at=datetime.now(UTC),
                            result=ProbeResult(
                                is_up=False,
                                status_code=None,
                                response_time_ms=0,
                                failure_kind="internal_error",
                            ),
                            next_check_at=datetime.now(UTC)
                            + timedelta(seconds=settings.uptime_check_interval_seconds),
                        )
            except Exception:
                logger.exception(
                    "uptime internal failure result could not be persisted",
                    extra={"monitor_id": str(item.id)},
                )

    await asyncio.gather(*(process(item) for item in claimed))

    cutoff = datetime.now(UTC) - timedelta(days=settings.uptime_history_retention_days)
    async with factory() as session:
        async with session.begin():
            await prune_website_monitor_checks(
                session,
                older_than=cutoff,
                limit=max(settings.uptime_worker_batch_size * 20, 1000),
            )
    return len(claimed)


async def wait_for_cycle_or_stop(cycle: Awaitable[object], stop_event: asyncio.Event) -> bool:
    """Run one cycle unless shutdown is requested, cancelling it promptly."""

    cycle_task = asyncio.ensure_future(cycle)
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait({cycle_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            return False
        await cycle_task
        return True
    finally:
        for task in (cycle_task, stop_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(cycle_task, stop_task, return_exceptions=True)


async def run_forever(settings: Settings, stop: asyncio.Event | None = None) -> None:
    """Run bounded cycles until SIGINT/SIGTERM requests a graceful stop."""

    stop_event = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if stop is None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop_event.set)

    engine = create_async_database_engine(
        settings.database_url,
        pool_size=settings.uptime_worker_concurrency,
        max_overflow=0,
    )
    factory = create_session_factory(settings.database_url, engine=engine)
    try:
        while not stop_event.is_set():
            try:
                completed = await wait_for_cycle_or_stop(
                    run_uptime_cycle(factory, settings), stop_event
                )
                if not completed:
                    break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("uptime worker cycle failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=settings.uptime_worker_poll_seconds
                )
            except TimeoutError:
                pass
    finally:
        await engine.dispose()


def main() -> None:
    """Start the worker from the runtime image."""

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever(Settings()))


if __name__ == "__main__":
    main()
