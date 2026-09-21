"""Database concurrency coverage for the uptime polling worker."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from watchtower.core.config import Settings
from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.models.website_monitor import WebsiteMonitor
from watchtower.models.website_monitor_check import WebsiteMonitorCheck
from watchtower.repositories.website_monitors import (
    ClaimedWebsiteMonitor,
    claim_due_website_monitors,
    record_website_monitor_check,
)
from watchtower.uptime.probe import ProbeResult
from watchtower.workers.uptime import run_uptime_cycle

DATABASE_URL = os.environ["WATCHTOWER_DATABASE_URL"]


@pytest.mark.integration
async def test_due_monitor_is_claimed_once_and_result_is_recorded_atomically() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_id, service_id, monitor_id = uuid4(), uuid4(), uuid4()
    due_at = datetime.now(UTC) - timedelta(minutes=1)
    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    Profile(
                        id=profile_id,
                        auth_user_id=uuid4(),
                        display_name="worker test",
                    )
                )
                await session.flush()
                session.add(
                    MonitoredService(
                        id=service_id,
                        profile_id=profile_id,
                        slug=f"worker-{uuid4().hex}",
                        display_name="Worker test",
                        environment="test",
                        active=True,
                        secret_key_id="managed",
                    )
                )
                await session.flush()
                session.add(
                    WebsiteMonitor(
                        id=monitor_id,
                        service_id=service_id,
                        url="https://example.com/",
                        next_check_at=due_at,
                    )
                )

        async def claim() -> list[ClaimedWebsiteMonitor]:
            async with factory() as session:
                async with session.begin():
                    return list(
                        await claim_due_website_monitors(
                            session,
                            now=datetime.now(UTC),
                            interval_seconds=60,
                            limit=10,
                            monitor_ids={monitor_id},
                        )
                    )

        first, second = await asyncio.gather(claim(), claim())
        claimed = first + second
        assert len(claimed) == 1
        assert claimed[0].id == monitor_id
        assert claimed[0].url == "https://example.com/"

        checked_at = datetime.now(UTC)
        result = ProbeResult(
            is_up=True,
            status_code=204,
            response_time_ms=37,
            failure_kind=None,
        )
        async with factory() as session:
            async with session.begin():
                await record_website_monitor_check(
                    session,
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    result=result,
                )

        async with factory() as session:
            monitor = await session.get(WebsiteMonitor, monitor_id)
            checks = list(
                await session.scalars(
                    select(WebsiteMonitorCheck).where(WebsiteMonitorCheck.monitor_id == monitor_id)
                )
            )
        assert monitor is not None
        assert monitor.last_is_up is True
        assert monitor.last_status_code == 204
        assert monitor.last_response_time_ms == 37
        assert monitor.last_failure_kind is None
        assert monitor.next_check_at > checked_at
        assert len(checks) == 1
        assert checks[0].is_up is True
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(delete(WebsiteMonitor).where(WebsiteMonitor.id == monitor_id))
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service_id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()


@pytest.mark.integration
async def test_worker_cycle_probes_due_monitor_and_persists_result() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_id, service_id, monitor_id = uuid4(), uuid4(), uuid4()
    calls: list[str] = []
    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    Profile(
                        id=profile_id,
                        auth_user_id=uuid4(),
                        display_name="worker cycle test",
                    )
                )
                await session.flush()
                session.add(
                    MonitoredService(
                        id=service_id,
                        profile_id=profile_id,
                        slug=f"cycle-{uuid4().hex}",
                        display_name="Worker cycle test",
                        environment="test",
                        active=True,
                        secret_key_id="managed",
                    )
                )
                await session.flush()
                session.add(
                    WebsiteMonitor(
                        id=monitor_id,
                        service_id=service_id,
                        url="https://example.org/",
                        next_check_at=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )

        async def fake_probe(url: str, **kwargs: object) -> ProbeResult:
            calls.append(url)
            assert kwargs["timeout_seconds"] == 10.0
            return ProbeResult(
                is_up=True,
                status_code=200,
                response_time_ms=12,
                failure_kind=None,
            )

        processed = await run_uptime_cycle(
            factory,
            Settings(
                environment="test",
                database_url=DATABASE_URL,
                auth_service_url="http://auth.test",
            ),
            probe=fake_probe,
            monitor_ids={monitor_id},
        )

        assert processed == 1
        assert calls == ["https://example.org/"]
        async with factory() as session:
            monitor = await session.get(WebsiteMonitor, monitor_id)
            checks = list(
                await session.scalars(
                    select(WebsiteMonitorCheck).where(WebsiteMonitorCheck.monitor_id == monitor_id)
                )
            )
            assert monitor is not None
            assert monitor.last_is_up is True
            assert monitor.last_status_code == 200
            assert len(checks) == 1
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebsiteMonitorCheck).where(WebsiteMonitorCheck.monitor_id == monitor_id)
                )
                await session.execute(delete(WebsiteMonitor).where(WebsiteMonitor.id == monitor_id))
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service_id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()


@pytest.mark.integration
async def test_worker_skips_claimed_monitor_deactivated_before_probe() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_id, service_id = uuid4(), uuid4()
    first_id = UUID(int=1)
    second_id = UUID(int=2)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls: list[str] = []
    try:
        async with factory() as session:
            async with session.begin():
                session.add(Profile(id=profile_id, auth_user_id=uuid4(), display_name="stop race"))
                await session.flush()
                session.add(
                    MonitoredService(
                        id=service_id,
                        profile_id=profile_id,
                        slug=f"stop-race-{uuid4().hex}",
                        display_name="Stop race",
                        environment="test",
                        active=True,
                        secret_key_id="managed",
                    )
                )
                await session.flush()
                due = datetime.now(UTC) - timedelta(minutes=1)
                session.add_all(
                    [
                        WebsiteMonitor(
                            id=first_id,
                            service_id=service_id,
                            url="https://one.example/",
                            next_check_at=due,
                        ),
                        WebsiteMonitor(
                            id=second_id,
                            service_id=service_id,
                            url="https://two.example/",
                            next_check_at=due,
                        ),
                    ]
                )

        async def fake_probe(url: str, **kwargs: object) -> ProbeResult:
            calls.append(url)
            if url == "https://one.example/":
                first_started.set()
                await release_first.wait()
            return ProbeResult(is_up=True, status_code=200, response_time_ms=1, failure_kind=None)

        cycle = asyncio.create_task(
            run_uptime_cycle(
                factory,
                Settings(
                    environment="test",
                    database_url=DATABASE_URL,
                    auth_service_url="http://auth.test",
                    uptime_worker_concurrency=1,
                ),
                probe=fake_probe,
                monitor_ids={first_id, second_id},
            )
        )
        await asyncio.wait_for(first_started.wait(), timeout=5)
        async with factory() as session:
            async with session.begin():
                second = await session.get(WebsiteMonitor, second_id, with_for_update=True)
                assert second is not None
                second.active = False
        release_first.set()
        await cycle

        assert calls == ["https://one.example/"]
        async with factory() as session:
            second_checks = await session.scalar(
                select(func.count())
                .select_from(WebsiteMonitorCheck)
                .where(WebsiteMonitorCheck.monitor_id == second_id)
            )
        assert second_checks == 0
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebsiteMonitorCheck).where(
                        WebsiteMonitorCheck.monitor_id.in_([first_id, second_id])
                    )
                )
                await session.execute(
                    delete(WebsiteMonitor).where(WebsiteMonitor.id.in_([first_id, second_id]))
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service_id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()


@pytest.mark.integration
async def test_stop_waits_for_in_progress_probe_before_deactivating() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_id, service_id, monitor_id = uuid4(), uuid4(), uuid4()
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()
    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    Profile(id=profile_id, auth_user_id=uuid4(), display_name="stop race")
                )
                await session.flush()
                session.add(
                    MonitoredService(
                        id=service_id,
                        profile_id=profile_id,
                        slug=f"stop-race-{uuid4().hex}",
                        display_name="Stop race",
                        environment="test",
                        active=True,
                        secret_key_id="managed",
                    )
                )
                await session.flush()
                session.add(
                    WebsiteMonitor(
                        id=monitor_id,
                        service_id=service_id,
                        url="https://example.com/",
                        next_check_at=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )

        async def blocking_probe(url: str, **kwargs: object) -> ProbeResult:
            probe_started.set()
            await release_probe.wait()
            return ProbeResult(
                is_up=True, status_code=200, response_time_ms=1, failure_kind=None
            )

        cycle = asyncio.create_task(
            run_uptime_cycle(
                factory,
                Settings(
                    environment="test",
                    database_url=DATABASE_URL,
                    auth_service_url="http://auth.test",
                    uptime_worker_concurrency=1,
                ),
                probe=blocking_probe,
                monitor_ids={monitor_id},
            )
        )
        await asyncio.wait_for(probe_started.wait(), timeout=5)

        async def stop_monitor() -> None:
            async with factory() as session:
                async with session.begin():
                    target = await session.get(WebsiteMonitor, monitor_id)
                    assert target is not None
                    target.active = False

        stop_task = asyncio.create_task(stop_monitor())
        await asyncio.sleep(0.05)
        assert not stop_task.done()
        release_probe.set()
        await asyncio.gather(cycle, stop_task)

        async with factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(WebsiteMonitorCheck)
                .where(WebsiteMonitorCheck.monitor_id == monitor_id)
            )
            target = await session.get(WebsiteMonitor, monitor_id)
        assert count == 1
        assert target is not None and target.active is False
    finally:
        release_probe.set()
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebsiteMonitorCheck).where(
                        WebsiteMonitorCheck.monitor_id == monitor_id
                    )
                )
                await session.execute(
                    delete(WebsiteMonitor).where(WebsiteMonitor.id == monitor_id)
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service_id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()


@pytest.mark.integration
async def test_unexpected_probe_failure_records_down_result() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_id, service_id, monitor_id = uuid4(), uuid4(), uuid4()
    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    Profile(id=profile_id, auth_user_id=uuid4(), display_name="probe failure")
                )
                await session.flush()
                session.add(
                    MonitoredService(
                        id=service_id,
                        profile_id=profile_id,
                        slug=f"probe-failure-{uuid4().hex}",
                        display_name="Probe failure",
                        environment="test",
                        active=True,
                        secret_key_id="managed",
                    )
                )
                await session.flush()
                session.add(
                    WebsiteMonitor(
                        id=monitor_id,
                        service_id=service_id,
                        url="https://failure.example/",
                        next_check_at=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )

        async def failing_probe(url: str, **kwargs: object) -> ProbeResult:
            raise RuntimeError("unexpected probe bug")

        await run_uptime_cycle(
            factory,
            Settings(
                environment="test", database_url=DATABASE_URL, auth_service_url="http://auth.test"
            ),
            probe=failing_probe,
            monitor_ids={monitor_id},
        )

        async with factory() as session:
            check = await session.scalar(
                select(WebsiteMonitorCheck).where(WebsiteMonitorCheck.monitor_id == monitor_id)
            )
        assert check is not None
        assert check.is_up is False
        assert check.failure_kind == "internal_error"
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(WebsiteMonitorCheck).where(WebsiteMonitorCheck.monitor_id == monitor_id)
                )
                await session.execute(delete(WebsiteMonitor).where(WebsiteMonitor.id == monitor_id))
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service_id)
                )
                await session.execute(delete(Profile).where(Profile.id == profile_id))
        await engine.dispose()
