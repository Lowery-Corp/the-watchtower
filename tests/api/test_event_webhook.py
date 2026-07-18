"""End-to-end API tests for authenticated event ingestion."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette import status

from watchtower.core.config import Settings
from watchtower.core.security import compute_webhook_signature
from watchtower.main import create_app
from watchtower.models.event import Event
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.outbox_message import OutboxMessage
from watchtower.repositories.monitored_services import create_monitored_service

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)
SECRET = "integration-only-signing-secret"


def event_body(source: str, *, event_id: str | None = None) -> bytes:
    payload = {
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
    return json.dumps(payload, separators=(",", ":")).encode()


def signed_headers(
    source: str,
    body: bytes,
    *,
    timestamp: str | None = None,
    secret: str = SECRET,
) -> dict[str, str]:
    signed_at = timestamp or str(int(datetime.now(UTC).timestamp()))
    return {
        "Content-Type": "application/json",
        "X-Watchtower-Service": source,
        "X-Watchtower-Timestamp": signed_at,
        "X-Watchtower-Signature": compute_webhook_signature(
            secret=secret,
            service=source,
            timestamp=signed_at,
            body=body,
        ),
        "X-Request-ID": "api-ingestion-test",
    }


@asynccontextmanager
async def webhook_client(
    *,
    active: bool = True,
    register: bool = True,
    max_body_bytes: int = 256 * 1024,
    rate_limit_requests: int = 60,
) -> AsyncIterator[tuple[AsyncClient, str]]:
    source = f"api-{uuid4().hex}"
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        webhook_secrets={source: SecretStr(SECRET)},
        max_webhook_body_bytes=max_body_bytes,
        webhook_rate_limit_requests=rate_limit_requests,
    )
    app = create_app(settings)
    factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)

    async with app.router.lifespan_context(app):
        service: MonitoredService | None = None
        if register:
            async with factory() as session:
                async with session.begin():
                    service = await create_monitored_service(
                        session,
                        slug=source,
                        display_name="API integration service",
                        environment="test",
                        secret_key_id="primary",
                        active=active,
                    )

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            try:
                yield client, source
            finally:
                if service is not None:
                    async with factory() as session:
                        async with session.begin():
                            await session.execute(
                                delete(OutboxMessage).where(
                                    OutboxMessage.service_id == service.id
                                )
                            )
                            await session.execute(
                                delete(Event).where(Event.service_id == service.id)
                            )
                            await session.execute(
                                delete(MonitoredService).where(
                                    MonitoredService.id == service.id
                                )
                            )


@pytest.mark.integration
async def test_openapi_documents_webhook_body_and_response_contract() -> None:
    app = create_app(Settings(database_url=DATABASE_URL))
    try:
        operation = app.openapi()["paths"]["/api/v1/webhooks/events"]["post"]
        responses = operation["responses"]
        request_schema = operation["requestBody"]["content"]["application/json"][
            "schema"
        ]
        parameters = {
            parameter["name"]: parameter for parameter in operation["parameters"]
        }

        assert {"202", "401", "403", "409", "413", "422", "429"} <= set(responses)
        assert request_schema["title"] == "EventEnvelope"
        for header in (
            "X-Watchtower-Service",
            "X-Watchtower-Timestamp",
            "X-Watchtower-Signature",
        ):
            assert parameters[header]["in"] == "header"
            assert parameters[header]["required"] is True
        assert responses["429"]["headers"]["Retry-After"]["schema"]["type"] == (
            "integer"
        )
    finally:
        await app.state.engine.dispose()


@pytest.mark.integration
async def test_valid_signed_event_returns_accepted_acknowledgement() -> None:
    async with webhook_client() as (client, source):
        body = event_body(source)
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body),
        )

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["status"] == "accepted"
    assert response.json()["request_id"] == "api-ingestion-test"
    assert response.headers["X-Request-ID"] == "api-ingestion-test"


@pytest.mark.integration
async def test_duplicate_retry_is_deterministic() -> None:
    async with webhook_client() as (client, source):
        body = event_body(source)
        headers = signed_headers(source, body)
        first = await client.post("/api/v1/webhooks/events", content=body, headers=headers)
        duplicate = await client.post(
            "/api/v1/webhooks/events", content=body, headers=headers
        )

    assert first.status_code == status.HTTP_202_ACCEPTED
    assert duplicate.status_code == status.HTTP_202_ACCEPTED
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["event_id"] == first.json()["event_id"]


@pytest.mark.integration
async def test_reused_event_id_with_changed_content_returns_conflict() -> None:
    source_event_id = str(uuid4())
    async with webhook_client() as (client, source):
        first_body = event_body(source, event_id=source_event_id)
        changed_payload = json.loads(first_body)
        changed_payload["data"] = {"status": "degraded"}
        changed_body = json.dumps(changed_payload, separators=(",", ":")).encode()
        first = await client.post(
            "/api/v1/webhooks/events",
            content=first_body,
            headers=signed_headers(source, first_body),
        )
        conflict = await client.post(
            "/api/v1/webhooks/events",
            content=changed_body,
            headers=signed_headers(source, changed_body),
        )

    assert first.status_code == status.HTTP_202_ACCEPTED
    assert conflict.status_code == status.HTTP_409_CONFLICT
    assert conflict.json() == {
        "detail": "Source event ID already exists with different content"
    }


@pytest.mark.integration
async def test_missing_authentication_headers_return_generic_unauthorized() -> None:
    async with webhook_client() as (client, source):
        response = await client.post(
            "/api/v1/webhooks/events",
            content=event_body(source),
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid webhook authentication"}


@pytest.mark.integration
async def test_invalid_signature_returns_generic_unauthorized() -> None:
    async with webhook_client() as (client, source):
        body = event_body(source)
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body, secret="wrong-secret"),
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid webhook authentication"}
    assert response.headers["X-Request-ID"] == "api-ingestion-test"


@pytest.mark.integration
async def test_stale_signature_is_rejected() -> None:
    stale_timestamp = str(int(datetime.now(UTC).timestamp()) - 301)
    async with webhook_client() as (client, source):
        body = event_body(source)
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body, timestamp=stale_timestamp),
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid webhook authentication"}


@pytest.mark.integration
async def test_signed_source_must_match_envelope_source() -> None:
    async with webhook_client() as (client, source):
        body = event_body("different-source")
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body),
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid webhook authentication"}


@pytest.mark.integration
async def test_configured_but_unregistered_source_is_unauthorized() -> None:
    async with webhook_client(register=False) as (client, source):
        body = event_body(source)
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body),
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid webhook authentication"}


@pytest.mark.integration
async def test_inactive_source_is_forbidden() -> None:
    async with webhook_client(active=False) as (client, source):
        body = event_body(source)
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body),
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Event source is not active"}


@pytest.mark.integration
async def test_malformed_envelope_is_rejected_without_details() -> None:
    body = b'{"not":"an-event"}'
    async with webhook_client() as (client, source):
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body),
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json() == {"detail": "Invalid event envelope"}


@pytest.mark.integration
async def test_application_rate_limit_returns_retryable_429() -> None:
    async with webhook_client(rate_limit_requests=1) as (client, source):
        first_body = event_body(source)
        second_body = event_body(source)
        first = await client.post(
            "/api/v1/webhooks/events",
            content=first_body,
            headers=signed_headers(source, first_body),
        )
        limited = await client.post(
            "/api/v1/webhooks/events",
            content=second_body,
            headers=signed_headers(source, second_body),
        )

    assert first.status_code == status.HTTP_202_ACCEPTED
    assert limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert limited.json() == {"detail": "Webhook rate limit exceeded"}
    assert int(limited.headers["Retry-After"]) >= 1


@pytest.mark.integration
async def test_oversized_body_is_rejected_before_parsing() -> None:
    body = b"x" * 1025
    async with webhook_client(max_body_bytes=1024) as (client, source):
        response = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers=signed_headers(source, body),
        )

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert response.json() == {"detail": "Webhook body exceeds configured limit"}
