"""Authenticated event-ingestion webhook."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.api.v1.dependencies.webhook_auth import (
    AuthenticatedWebhook,
    authenticate_webhook,
)
from watchtower.db.dependencies import get_db_session
from watchtower.middleware.request_context import request_id_context
from watchtower.schemas.event import EventEnvelope, EventIngestionAcknowledgement
from watchtower.services.event_ingestion import (
    EventConflictError,
    InactiveSourceError,
    ManagedKeyAuthenticationError,
    SourceMismatchError,
    UnknownSourceError,
    ingest_event,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_WEBHOOK_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Invalid webhook authentication"},
    status.HTTP_403_FORBIDDEN: {"description": "Authenticated source is inactive"},
    status.HTTP_409_CONFLICT: {"description": "Source event ID content conflict"},
    status.HTTP_413_CONTENT_TOO_LARGE: {"description": "Request body exceeds limit"},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Invalid event envelope"},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "description": "Application or edge request budget exceeded",
        "headers": {
            "Retry-After": {
                "description": "Seconds until the application budget resets",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    },
}
_AUTH_HEADER_PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "X-Watchtower-Service",
        "in": "header",
        "required": True,
        "description": "Registered lowercase source-service slug",
        "schema": {"type": "string"},
    },
    {
        "name": "X-Watchtower-API-Key",
        "in": "header",
        "required": False,
        "description": (
            "Managed profile API key. When present, timestamp and signature are omitted."
        ),
        "schema": {
            "type": "string",
            "pattern": r"^wtk_v1_[A-Za-z0-9_-]{16}\.[A-Za-z0-9_-]{43}$",
        },
    },
    {
        "name": "X-Watchtower-Timestamp",
        "in": "header",
        "required": False,
        "description": "Legacy HMAC Unix timestamp; required with signature when no managed key is sent",
        "schema": {"type": "string", "pattern": r"^\d+$"},
    },
    {
        "name": "X-Watchtower-Signature",
        "in": "header",
        "required": False,
        "description": "Legacy HMAC-SHA256 signature; required with timestamp when no managed key is sent",
        "schema": {"type": "string", "pattern": r"^v1=[0-9a-f]{64}$"},
    },
]
_WEBHOOK_OPENAPI_EXTRA: dict[str, Any] = {
    "parameters": _AUTH_HEADER_PARAMETERS,
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": EventEnvelope.model_json_schema()}
        },
    }
}


@router.post(
    "/events",
    response_model=EventIngestionAcknowledgement,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_WEBHOOK_RESPONSES,
    openapi_extra=_WEBHOOK_OPENAPI_EXTRA,
)
async def receive_event(
    authenticated: Annotated[AuthenticatedWebhook, Depends(authenticate_webhook)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EventIngestionAcknowledgement:
    """Authenticate, validate, and transactionally ingest one event."""

    try:
        envelope = EventEnvelope.model_validate_json(authenticated.body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid event envelope",
        ) from exc

    request_id = request_id_context.get()
    if request_id is None:
        raise RuntimeError("request context is unavailable")

    try:
        outcome = await ingest_event(
            session,
            profile_id=authenticated.profile_id,
            authenticated_source=authenticated.source,
            envelope=envelope,
            request_id=request_id,
            api_key_id=authenticated.api_key_id,
            api_key_token=authenticated.api_key_token,
        )
    except EventConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source event ID already exists with different content",
        ) from exc
    except (
        ManagedKeyAuthenticationError,
        SourceMismatchError,
        UnknownSourceError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook authentication",
        ) from exc
    except InactiveSourceError as exc:
        if authenticated.api_key_id is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook authentication",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event source is not active",
        ) from exc

    return EventIngestionAcknowledgement(
        event_id=outcome.event_id,
        source_event_id=outcome.source_event_id,
        status=outcome.status,
        request_id=request_id,
    )
