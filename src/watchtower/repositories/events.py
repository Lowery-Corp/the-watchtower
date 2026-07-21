"""Canonical event persistence operations."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.event import Event
from watchtower.schemas.event import EventEnvelope


async def create_event_if_absent(
    session: AsyncSession,
    *,
    profile_id: UUID,
    service_id: UUID,
    envelope: EventEnvelope,
    request_id: str,
    payload: dict[str, Any],
) -> tuple[Event, bool]:
    """Insert once by source/service ID and return the canonical event."""

    canonical_id = uuid4()
    statement = (
        insert(Event)
        .values(
            id=canonical_id,
            profile_id=profile_id,
            source_event_id=envelope.event_id,
            service_id=service_id,
            spec_version=envelope.spec_version,
            event_type=envelope.event_type,
            subject=envelope.subject,
            occurred_at=envelope.occurred_at,
            severity=envelope.severity,
            environment=envelope.environment,
            correlation_id=envelope.correlation_id,
            request_id=request_id,
            payload=payload,
        )
        .on_conflict_do_nothing(
            constraint="uq_event_profile_service_source_event"
        )
        .returning(Event)
    )
    result = await session.execute(statement)
    created = result.scalar_one_or_none()
    if created is not None:
        return created, True

    existing = await session.scalar(
        select(Event).where(
            Event.profile_id == profile_id,
            Event.service_id == service_id,
            Event.source_event_id == envelope.event_id,
        )
    )
    if existing is None:
        raise RuntimeError("idempotent event lookup failed")
    return existing, False
