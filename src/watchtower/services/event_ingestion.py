"""Transactional profile-attributed event-ingestion use case."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.core.api_keys import verify_api_key
from watchtower.messaging.topics import RAW_EVENTS_TOPIC
from watchtower.repositories.api_keys import get_api_key_for_ingestion
from watchtower.repositories.events import create_event_if_absent
from watchtower.repositories.monitored_services import get_monitored_service_by_slug
from watchtower.repositories.outbox import create_outbox_message
from watchtower.schemas.event import EventEnvelope


class ManagedKeyAuthenticationError(ValueError):
    """Raised when managed-key state changes before ingestion commits."""


class EventConflictError(ValueError):
    """Raised when an existing source event ID is reused with different content."""


class UnknownSourceError(ValueError):
    """Raised when no monitored-service identity exists in the authenticated profile."""


class InactiveSourceError(ValueError):
    """Raised when an inactive source submits an event."""


class SourceMismatchError(ValueError):
    """Raised when the authenticated source differs from the event source."""


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """Stable result returned for accepted and duplicate submissions."""

    event_id: UUID
    source_event_id: UUID
    status: Literal["accepted", "duplicate"]


async def ingest_event(
    session: AsyncSession,
    *,
    profile_id: UUID,
    authenticated_source: str,
    envelope: EventEnvelope,
    request_id: str,
    api_key_id: UUID | None = None,
    api_key_token: SecretStr | None = None,
) -> IngestionOutcome:
    """Persist an event and outbox message under one profile transaction."""

    if envelope.source != authenticated_source:
        raise SourceMismatchError("Authenticated source does not match event source")

    if (api_key_id is None) != (api_key_token is None):
        raise ManagedKeyAuthenticationError("Incomplete managed-key context")

    async with session.begin():
        managed_key = None
        service = None
        if api_key_id is not None and api_key_token is not None:
            service = await get_monitored_service_by_slug(
                session,
                profile_id=profile_id,
                slug=authenticated_source,
                for_update=True,
            )
            managed_key = await get_api_key_for_ingestion(session, api_key_id=api_key_id)
            now = datetime.now(UTC)
            if (
                managed_key is None
                or managed_key.token_version != 1
                or not verify_api_key(api_key_token.get_secret_value(), managed_key.secret_digest)
                or managed_key.revoked_at is not None
                or (managed_key.expires_at is not None and managed_key.expires_at <= now)
                or "events:write" not in managed_key.scopes
                or managed_key.service_id is None
            ):
                raise ManagedKeyAuthenticationError("Managed key is no longer valid")
            if service is None or not service.active or managed_key.service_id != service.id:
                raise ManagedKeyAuthenticationError("Managed key binding is invalid")
        else:
            service = await get_monitored_service_by_slug(
                session,
                profile_id=profile_id,
                slug=authenticated_source,
            )
            if service is None:
                raise UnknownSourceError("Event source is not registered")
            if not service.active:
                raise InactiveSourceError("Event source is not active")

        raw_payload = envelope.model_dump(mode="json")
        event, created = await create_event_if_absent(
            session,
            profile_id=profile_id,
            service_id=service.id,
            envelope=envelope,
            request_id=request_id,
            payload=raw_payload,
        )
        if not created:
            if event.payload != raw_payload:
                raise EventConflictError("Source event ID already exists with different content")
            if managed_key is not None:
                managed_key.last_used_at = datetime.now(UTC)
                await session.flush()
            return IngestionOutcome(
                event_id=event.id,
                source_event_id=event.source_event_id,
                status="duplicate",
            )

        await create_outbox_message(
            session,
            profile_id=profile_id,
            event_id=event.id,
            service_id=service.id,
            topic=RAW_EVENTS_TOPIC,
            partition_key=f"{profile_id}:{service.slug}",
            payload={
                "message_version": "1.0",
                "profile_id": str(profile_id),
                "event_id": str(event.id),
                "source_event_id": str(envelope.event_id),
                "service_id": str(service.id),
                "source": service.slug,
                "event": raw_payload,
            },
        )
        if managed_key is not None:
            managed_key.last_used_at = datetime.now(UTC)
            await session.flush()

    return IngestionOutcome(
        event_id=event.id,
        source_event_id=event.source_event_id,
        status="accepted",
    )
