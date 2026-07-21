"""Transactional outbox persistence operations."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.outbox_message import OutboxMessage


async def create_outbox_message(
    session: AsyncSession,
    *,
    profile_id: UUID,
    event_id: UUID,
    service_id: UUID,
    topic: str,
    partition_key: str,
    payload: dict[str, Any],
) -> OutboxMessage:
    """Add an outbox row without committing the caller's transaction."""

    message = OutboxMessage(
        profile_id=profile_id,
        event_id=event_id,
        service_id=service_id,
        topic=topic,
        partition_key=partition_key,
        payload=payload,
    )
    session.add(message)
    await session.flush()
    return message
