"""PostgreSQL integration tests for transactional event ingestion."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NoReturn
from uuid import uuid4

import pytest
from pytest import MonkeyPatch
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.messaging.topics import RAW_EVENTS_TOPIC
from watchtower.models.event import Event
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.outbox_message import OutboxMessage
from watchtower.repositories.monitored_services import create_monitored_service
from watchtower.repositories.outbox import create_outbox_message
from watchtower.schemas.event import EventEnvelope
from watchtower.services.event_ingestion import (
    EventConflictError,
    InactiveSourceError,
    ingest_event,
)

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


def make_envelope(source: str, *, event_id: str | None = None) -> EventEnvelope:
    return EventEnvelope.model_validate(
        {
            "spec_version": "1.0",
            "event_id": event_id or str(uuid4()),
            "event_type": "service.heartbeat",
            "source": source,
            "subject": "api-1",
            "occurred_at": "2026-07-18T20:00:00Z",
            "severity": "info",
            "environment": "test",
            "correlation_id": "trace-123",
            "data": {"status": "healthy"},
        }
    )


@asynccontextmanager
async def registered_service(
    factory: async_sessionmaker[AsyncSession],
    *,
    active: bool = True,
) -> AsyncIterator[MonitoredService]:
    slug = f"ingest-{uuid4().hex}"
    async with factory() as session:
        async with session.begin():
            service = await create_monitored_service(
                session,
                slug=slug,
                display_name="Ingestion test",
                environment="test",
                secret_key_id="primary",
                active=active,
            )

    try:
        yield service
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(OutboxMessage).where(OutboxMessage.service_id == service.id)
                )
                await session.execute(delete(Event).where(Event.service_id == service.id))
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == service.id)
                )


@pytest.mark.integration
async def test_first_ingestion_persists_event_and_outbox_atomically() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with registered_service(factory) as service:
            envelope = make_envelope(service.slug)
            async with factory() as session:
                outcome = await ingest_event(
                    session,
                    authenticated_source=service.slug,
                    envelope=envelope,
                    request_id="request-123",
                )

            async with factory() as session:
                event = await session.scalar(select(Event).where(Event.id == outcome.event_id))
                outbox = await session.scalar(
                    select(OutboxMessage).where(OutboxMessage.event_id == outcome.event_id)
                )

            assert outcome.status == "accepted"
            assert event is not None
            assert event.payload["data"] == {"status": "healthy"}
            assert event.request_id == "request-123"
            assert outbox is not None
            assert outbox.topic == RAW_EVENTS_TOPIC
            assert outbox.partition_key == service.slug
            assert outbox.payload["event_id"] == str(outcome.event_id)
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_duplicate_retry_returns_original_without_new_rows() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with registered_service(factory) as service:
            envelope = make_envelope(service.slug)
            async with factory() as session:
                first = await ingest_event(
                    session,
                    authenticated_source=service.slug,
                    envelope=envelope,
                    request_id="request-first",
                )
            async with factory() as session:
                duplicate = await ingest_event(
                    session,
                    authenticated_source=service.slug,
                    envelope=envelope,
                    request_id="request-retry",
                )
            async with factory() as session:
                event_count = await session.scalar(
                    select(func.count()).select_from(Event).where(Event.service_id == service.id)
                )
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.service_id == service.id)
                )

            assert duplicate.status == "duplicate"
            assert duplicate.event_id == first.event_id
            assert event_count == 1
            assert outbox_count == 1
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_reused_event_id_with_different_payload_is_rejected() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with registered_service(factory) as service:
            envelope = make_envelope(service.slug)
            changed = envelope.model_copy(update={"data": {"status": "degraded"}})
            async with factory() as session:
                await ingest_event(
                    session,
                    authenticated_source=service.slug,
                    envelope=envelope,
                    request_id="request-first",
                )
            async with factory() as session:
                with pytest.raises(EventConflictError):
                    await ingest_event(
                        session,
                        authenticated_source=service.slug,
                        envelope=changed,
                        request_id="request-conflict",
                    )
            async with factory() as session:
                event_count = await session.scalar(
                    select(func.count()).select_from(Event).where(Event.service_id == service.id)
                )
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.service_id == service.id)
                )

            assert event_count == 1
            assert outbox_count == 1
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_concurrent_identical_ingestion_creates_one_event_and_outbox() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with registered_service(factory) as service:
            envelope = make_envelope(service.slug)

            async def submit(request_id: str) -> str:
                async with factory() as session:
                    outcome = await ingest_event(
                        session,
                        authenticated_source=service.slug,
                        envelope=envelope,
                        request_id=request_id,
                    )
                    return outcome.status

            statuses = await asyncio.gather(submit("concurrent-1"), submit("concurrent-2"))

            async with factory() as session:
                event_count = await session.scalar(
                    select(func.count()).select_from(Event).where(Event.service_id == service.id)
                )
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.service_id == service.id)
                )

            assert sorted(statuses) == ["accepted", "duplicate"]
            assert event_count == 1
            assert outbox_count == 1
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_concurrent_conflicting_ingestion_accepts_one_and_rejects_one() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with registered_service(factory) as service:
            envelope = make_envelope(service.slug)
            changed = envelope.model_copy(update={"data": {"status": "degraded"}})

            async def submit(candidate: EventEnvelope, request_id: str) -> str:
                async with factory() as session:
                    try:
                        outcome = await ingest_event(
                            session,
                            authenticated_source=service.slug,
                            envelope=candidate,
                            request_id=request_id,
                        )
                    except EventConflictError:
                        return "conflict"
                    return outcome.status

            statuses = await asyncio.gather(
                submit(envelope, "conflict-concurrent-1"),
                submit(changed, "conflict-concurrent-2"),
            )

            assert sorted(statuses) == ["accepted", "conflict"]
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_inactive_source_is_rejected_without_rows() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with registered_service(factory, active=False) as service:
            async with factory() as session:
                with pytest.raises(InactiveSourceError):
                    await ingest_event(
                        session,
                        authenticated_source=service.slug,
                        envelope=make_envelope(service.slug),
                        request_id="request-inactive",
                    )
            async with factory() as session:
                event_count = await session.scalar(
                    select(func.count()).select_from(Event).where(Event.service_id == service.id)
                )

            assert event_count == 0
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_outbox_service_must_match_event_service() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with registered_service(factory) as event_service:
            async with registered_service(factory) as wrong_service:
                async with factory() as session:
                    outcome = await ingest_event(
                        session,
                        authenticated_source=event_service.slug,
                        envelope=make_envelope(event_service.slug),
                        request_id="request-integrity",
                    )
                async with factory() as session:
                    async with session.begin():
                        await session.execute(
                            delete(OutboxMessage).where(
                                OutboxMessage.event_id == outcome.event_id
                            )
                        )
                async with factory() as session:
                    with pytest.raises(IntegrityError):
                        async with session.begin():
                            await create_outbox_message(
                                session,
                                event_id=outcome.event_id,
                                service_id=wrong_service.id,
                                topic=RAW_EVENTS_TOPIC,
                                partition_key=wrong_service.slug,
                                payload={"message_version": "1.0"},
                            )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_outbox_failure_rolls_back_event(
    monkeypatch: MonkeyPatch,
) -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    async def fail_outbox(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("forced outbox failure")

    monkeypatch.setattr(
        "watchtower.services.event_ingestion.create_outbox_message",
        fail_outbox,
    )

    try:
        async with registered_service(factory) as service:
            async with factory() as session:
                with pytest.raises(RuntimeError, match="forced outbox failure"):
                    await ingest_event(
                        session,
                        authenticated_source=service.slug,
                        envelope=make_envelope(service.slug),
                        request_id="request-rollback",
                    )
            async with factory() as session:
                event_count = await session.scalar(
                    select(func.count()).select_from(Event).where(Event.service_id == service.id)
                )

            assert event_count == 0
    finally:
        await engine.dispose()
