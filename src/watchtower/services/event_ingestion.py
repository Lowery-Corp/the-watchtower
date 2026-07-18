"""Transactional event-ingestion use case."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.messaging.topics import RAW_EVENTS_TOPIC
from watchtower.repositories.events import create_event_if_absent
from watchtower.repositories.monitored_services import get_monitored_service_by_slug
from watchtower.repositories.outbox import create_outbox_message
from watchtower.schemas.event import EventEnvelope


class EventConflictError(ValueError):
    """Raised when an existing source event ID is reused with different content."""


class UnknownSourceError(ValueError):
    """Raised when no monitored-service identity exists for a configured signer."""


class InactiveSourceError(ValueError):
    """Raised when an unregistered or inactive source submits an event."""


class SourceMismatchError(ValueError):
    """Raised when the signed source differs from the event source."""


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """Stable result returned for accepted and duplicate submissions."""

    event_id: UUID
    source_event_id: UUID
    status: Literal["accepted", "duplicate"]


async def ingest_event(
    session: AsyncSession,
    *,
    authenticated_source: str,
    envelope: EventEnvelope,
    request_id: str,
) -> IngestionOutcome:
    """Persist an event and outbox message in one caller-visible transaction."""

    if envelope.source != authenticated_source:
        raise SourceMismatchError("Authenticated source does not match event source")

    async with session.begin():
        service = await get_monitored_service_by_slug(session, authenticated_source)
        if service is None:
            raise UnknownSourceError("Event source is not registered")
        if not service.active:
            raise InactiveSourceError("Event source is not active")

        raw_payload = envelope.model_dump(mode="json")
        event, created = await create_event_if_absent(
            session,
            service_id=service.id,
            envelope=envelope,
            request_id=request_id,
            payload=raw_payload,
        )
        if not created:
            if event.payload != raw_payload:
                raise EventConflictError(
                    "Source event ID already exists with different content"
                )
            return IngestionOutcome(
                event_id=event.id,
                source_event_id=event.source_event_id,
                status="duplicate",
            )

        await create_outbox_message(
            session,
            event_id=event.id,
            service_id=service.id,
            topic=RAW_EVENTS_TOPIC,
            partition_key=service.slug,
            payload={
                "message_version": "1.0",
                "event_id": str(event.id),
                "source_event_id": str(envelope.event_id),
                "service_id": str(service.id),
                "source": service.slug,
                "event": raw_payload,
            },
        )

    return IngestionOutcome(
        event_id=event.id,
        source_event_id=event.source_event_id,
        status="accepted",
    )
