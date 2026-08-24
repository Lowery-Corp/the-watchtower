"""Database-enforced tenant ownership tests."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.api_key import ApiKey
from watchtower.models.event import Event
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.outbox_message import OutboxMessage
from watchtower.models.profile import Profile

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


def event_for(*, profile_id: UUID, service_id: UUID) -> Event:
    return Event(
        profile_id=profile_id,
        service_id=service_id,
        source_event_id=uuid4(),
        spec_version="1.0",
        event_type="service.heartbeat",
        occurred_at=datetime.now(UTC),
        severity="info",
        environment="test",
        request_id="tenant-integrity-test",
        payload={"status": "healthy"},
    )


@pytest.mark.integration
async def test_same_service_slug_is_allowed_in_different_profiles() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_ids = [uuid4(), uuid4()]
    slug = f"shared-{uuid4().hex}"

    try:
        async with factory() as session:
            async with session.begin():
                for profile_id in profile_ids:
                    session.add(Profile(id=profile_id, auth_user_id=uuid4(), display_name="Tenant"))
                await session.flush()
                for profile_id in profile_ids:
                    session.add(
                        MonitoredService(
                            profile_id=profile_id,
                            slug=slug,
                            display_name="Shared slug",
                            environment="test",
                            active=True,
                            secret_key_id="legacy",
                        )
                    )
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.profile_id.in_(profile_ids))
                )
                await session.execute(delete(Profile).where(Profile.id.in_(profile_ids)))
        await engine.dispose()


@pytest.mark.integration
async def test_event_service_profile_mismatch_is_rejected() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_a = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="A")
    profile_b = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="B")
    service_b = MonitoredService(
        profile_id=profile_b.id,
        slug=f"tenant-b-{uuid4().hex}",
        display_name="Tenant B",
        environment="test",
        active=True,
        secret_key_id="legacy",
    )

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all([profile_a, profile_b])
                await session.flush()
                session.add(service_b)
                await session.flush()
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(event_for(profile_id=profile_a.id, service_id=service_b.id))
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(MonitoredService).where(
                        MonitoredService.profile_id.in_([profile_a.id, profile_b.id])
                    )
                )
                await session.execute(
                    delete(Profile).where(Profile.id.in_([profile_a.id, profile_b.id]))
                )
        await engine.dispose()


@pytest.mark.integration
async def test_outbox_event_profile_mismatch_is_rejected() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile_a = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="A")
    profile_b = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="B")
    service_a = MonitoredService(
        id=uuid4(),
        profile_id=profile_a.id,
        slug=f"tenant-a-{uuid4().hex}",
        display_name="Tenant A",
        environment="test",
        active=True,
        secret_key_id="legacy",
    )
    event_a = event_for(profile_id=profile_a.id, service_id=service_a.id)

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all([profile_a, profile_b])
                await session.flush()
                session.add(service_a)
                await session.flush()
                session.add(event_a)
                await session.flush()
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        OutboxMessage(
                            profile_id=profile_b.id,
                            event_id=event_a.id,
                            service_id=service_a.id,
                            topic="test",
                            partition_key="test",
                            payload={},
                        )
                    )
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(OutboxMessage).where(OutboxMessage.event_id == event_a.id)
                )
                await session.execute(delete(Event).where(Event.id == event_a.id))
                await session.execute(
                    delete(MonitoredService).where(
                        MonitoredService.profile_id.in_([profile_a.id, profile_b.id])
                    )
                )
                await session.execute(
                    delete(Profile).where(Profile.id.in_([profile_a.id, profile_b.id]))
                )
        await engine.dispose()


@pytest.mark.integration
async def test_profile_deletion_is_restricted_while_api_key_history_exists() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    profile = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Key owner")
    api_key = ApiKey(
        profile_id=profile.id,
        name=f"retained-{uuid4().hex}",
        public_prefix=f"wt_{uuid4().hex[:16]}",
        secret_digest=uuid4().bytes + uuid4().bytes,
        scopes=["events:write"],
    )

    try:
        async with factory() as session:
            async with session.begin():
                session.add(profile)
                await session.flush()
                session.add(api_key)

        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    await session.execute(delete(Profile).where(Profile.id == profile.id))

        async with factory() as session:
            assert (
                await session.scalar(select(Profile.id).where(Profile.id == profile.id))
                == profile.id
            )
            assert (
                await session.scalar(select(ApiKey.id).where(ApiKey.id == api_key.id)) == api_key.id
            )
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(delete(ApiKey).where(ApiKey.id == api_key.id))
                await session.execute(delete(Profile).where(Profile.id == profile.id))
        await engine.dispose()
