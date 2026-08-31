"""Periodic website uptime worker entry point."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchtower.core.config import Settings
from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.repositories.website_monitors import (
    ClaimedWebsiteMonitor,
    claim_due_website_monitors,
    prune_website_monitor_checks,
    record_website_monitor_check,
    website_monitor_is_active,
)
from watchtower.uptime.probe import ProbeResult, probe_url

logger = logging.getLogger(__name__)
Probe = Callable[..., Awaitable[ProbeResult]]


async def run_uptime_cycle(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    probe: Probe = probe_url,
) -> int:
    """Claim and probe one bounded batch, returning the number claimed."""

    now = datetime.now(UTC)
    async with factory() as session:
        async with session.begin():
            claimed = await claim_due_website_monitors(
                session,
                now=now,
                interval_seconds=settings.uptime_check_interval_seconds,
                limit=settings.uptime_worker_batch_size,
            )

    semaphore = asyncio.Semaphore(settings.uptime_worker_concurrency)

    async def process(item: ClaimedWebsiteMonitor) -> None:
        try:
            async with semaphore:
                async with factory() as session:
                    if not await website_monitor_is_active(
                        session, monitor_id=item.id
                    ):
                        return
                result = await probe(
                    item.url,
                    timeout_seconds=settings.uptime_check_timeout_seconds,
                )
            checked_at = datetime.now(UTC)
            async with factory() as session:
                async with session.begin():
                    await record_website_monitor_check(
                        session,
                        monitor_id=item.id,
                        checked_at=checked_at,
                        result=result,
                    )
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
            logger.error(
                "uptime check failed unexpectedly",
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


async def wait_for_cycle_or_stop(
    cycle: Awaitable[object], stop_event: asyncio.Event
) -> bool:
    """Run one cycle unless shutdown is requested, cancelling it promptly."""

    cycle_task = asyncio.ensure_future(cycle)
    stop_task = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {cycle_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if stop_task in done:
        cycle_task.cancel()
        try:
            await cycle_task
        except asyncio.CancelledError:
            pass
        return False
    stop_task.cancel()
    await cycle_task
    return True


async def run_forever(settings: Settings, stop: asyncio.Event | None = None) -> None:
    """Run bounded cycles until SIGINT/SIGTERM requests a graceful stop."""

    stop_event = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if stop is None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop_event.set)

    engine = create_async_database_engine(settings.database_url)
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
