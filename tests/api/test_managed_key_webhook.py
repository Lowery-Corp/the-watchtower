"""End-to-end managed API-key webhook authentication tests."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette import status

from watchtower.core.config import Settings
from watchtower.main import create_app
from watchtower.models.api_key import ApiKey
from watchtower.models.event import Event
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.outbox_message import OutboxMessage
from watchtower.models.profile import Profile
from watchtower.schemas.auth import AuthenticatedUser

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)
USER_A = AuthenticatedUser(id=uuid4(), username="sender-a", is_admin=False)
USER_B = AuthenticatedUser(id=uuid4(), username="sender-b", is_admin=False)


class WebhookUserAuthClient:
    async def get_current_user(self, token: str) -> AuthenticatedUser:
        return {"user-token-a": USER_A, "user-token-b": USER_B}[token]


@asynccontextmanager
async def managed_webhook_client() -> AsyncIterator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession]]
]:
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            auth_service_url="http://auth.test",
        )
    )
    app.state.auth_client = WebhookUserAuthClient()
    factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://watchtower.test") as client:
            try:
                yield client, factory
            finally:
                async with factory() as session:
                    async with session.begin():
                        profile_ids = list(
                            (
                                await session.scalars(
                                    select(Profile.id).where(
                                        Profile.auth_user_id.in_([USER_A.id, USER_B.id])
                                    )
                                )
                            ).all()
                        )
                        if profile_ids:
                            await session.execute(
                                delete(OutboxMessage).where(
                                    OutboxMessage.profile_id.in_(profile_ids)
                                )
                            )
                            await session.execute(
                                delete(Event).where(Event.profile_id.in_(profile_ids))
                            )
                            await session.execute(
                                delete(ApiKey).where(ApiKey.profile_id.in_(profile_ids))
                            )
                            await session.execute(
                                delete(MonitoredService).where(
                                    MonitoredService.profile_id.in_(profile_ids)
                                )
                            )
                            await session.execute(
                                delete(Profile).where(Profile.id.in_(profile_ids))
                            )


def user_auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {user}"}


def event_body(source: str, event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "spec_version": "1.0",
            "event_id": event_id or str(uuid4()),
            "event_type": "service.heartbeat",
            "source": source,
            "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "severity": "info",
            "environment": "test",
            "data": {"status": "healthy"},
        },
        separators=(",", ":"),
    ).encode()


async def create_service_and_key(
    client: AsyncClient,
    *,
    user_token: str,
    slug: str,
    key_name: str,
    bind_service: bool = False,
) -> tuple[dict[str, object], str]:
    service = await client.post(
        "/api/v1/services",
        json={"slug": slug, "display_name": slug, "environment": "test"},
        headers=user_auth(user_token),
    )
    assert service.status_code == status.HTTP_201_CREATED
    key_payload: dict[str, object] = {"name": key_name}
    if bind_service:
        key_payload["service_id"] = service.json()["id"]
    key = await client.post(
        "/api/v1/api-keys",
        json=key_payload,
        headers=user_auth(user_token),
    )
    assert key.status_code == status.HTTP_201_CREATED
    return service.json(), key.json()["api_key"]


@pytest.mark.integration
async def test_managed_key_attributes_event_and_outbox_to_profile() -> None:
    slug = f"managed-{uuid4().hex}"
    async with managed_webhook_client() as (client, factory):
        service, api_key = await create_service_and_key(
            client,
            user_token="user-token-a",
            slug=slug,
            key_name="managed-key",
        )
        body = event_body(slug)
        accepted = await client.post(
            "/api/v1/webhooks/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Watchtower-Service": slug,
                "X-Watchtower-API-Key": api_key,
            },
        )
        assert accepted.status_code == status.HTTP_202_ACCEPTED
        listed_keys = await client.get("/api/v1/api-keys", headers=user_auth("user-token-a"))
        async with factory() as session:
            event = await session.scalar(
                select(Event).where(Event.id == UUID(accepted.json()["event_id"]))
            )
            assert event is not None
            outbox = await session.scalar(
                select(OutboxMessage).where(OutboxMessage.event_id == event.id)
            )

    assert accepted.status_code == status.HTTP_202_ACCEPTED
    assert listed_keys.json()[0]["last_used_at"] is not None
    assert outbox is not None
    assert event.profile_id == outbox.profile_id
    assert event.service_id == UUID(str(service["id"]))
    assert outbox.payload["profile_id"] == str(event.profile_id)


@pytest.mark.integration
async def test_key_cannot_submit_for_another_profiles_service() -> None:
    slug_a = f"sender-a-{uuid4().hex}"
    slug_b = f"sender-b-{uuid4().hex}"
    async with managed_webhook_client() as (client, _):
        _, key_a = await create_service_and_key(
            client,
            user_token="user-token-a",
            slug=slug_a,
            key_name="key-a",
        )
        await create_service_and_key(
            client,
            user_token="user-token-b",
            slug=slug_b,
            key_name="key-b",
        )
        response = await client.post(
            "/api/v1/webhooks/events",
            content=event_body(slug_b),
            headers={
                "Content-Type": "application/json",
                "X-Watchtower-Service": slug_b,
                "X-Watchtower-API-Key": key_a,
            },
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid webhook authentication"}


@pytest.mark.integration
async def test_failed_body_validation_does_not_mark_key_used() -> None:
    slug = f"invalid-body-{uuid4().hex}"
    async with managed_webhook_client() as (client, _):
        _, api_key = await create_service_and_key(
            client,
            user_token="user-token-a",
            slug=slug,
            key_name="invalid-body-key",
        )
        response = await client.post(
            "/api/v1/webhooks/events",
            content=b'{"not":"an-event"}',
            headers={
                "Content-Type": "application/json",
                "X-Watchtower-Service": slug,
                "X-Watchtower-API-Key": api_key,
            },
        )
        keys = await client.get("/api/v1/api-keys", headers=user_auth("user-token-a"))

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert keys.json()[0]["last_used_at"] is None


@pytest.mark.integration
async def test_duplicate_managed_key_headers_are_rejected_generically() -> None:
    slug = f"duplicate-header-{uuid4().hex}"
    async with managed_webhook_client() as (client, _):
        _, api_key = await create_service_and_key(
            client,
            user_token="user-token-a",
            slug=slug,
            key_name="duplicate-header-key",
        )
        response = await client.post(
            "/api/v1/webhooks/events",
            content=event_body(slug),
            headers=[
                ("X-Watchtower-Service", slug),
                ("X-Watchtower-API-Key", api_key),
                ("X-Watchtower-API-Key", api_key),
            ],
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid webhook authentication"}


@pytest.mark.integration
async def test_revoked_key_is_rejected_and_service_binding_is_enforced() -> None:
    slug = f"bound-{uuid4().hex}"
    other_slug = f"other-{uuid4().hex}"
    async with managed_webhook_client() as (client, _):
        service, bound_key = await create_service_and_key(
            client,
            user_token="user-token-a",
            slug=slug,
            key_name="bound-key",
            bind_service=True,
        )
        other_service = await client.post(
            "/api/v1/services",
            json={"slug": other_slug, "display_name": other_slug, "environment": "test"},
            headers=user_auth("user-token-a"),
        )
        mismatched = await client.post(
            "/api/v1/webhooks/events",
            content=event_body(other_slug),
            headers={
                "X-Watchtower-Service": other_slug,
                "X-Watchtower-API-Key": bound_key,
            },
        )
        keys = await client.get("/api/v1/api-keys", headers=user_auth("user-token-a"))
        key_id = next(item["id"] for item in keys.json() if item["service_id"] == service["id"])
        await client.delete(f"/api/v1/api-keys/{key_id}", headers=user_auth("user-token-a"))
        revoked = await client.post(
            "/api/v1/webhooks/events",
            content=event_body(slug),
            headers={"X-Watchtower-Service": slug, "X-Watchtower-API-Key": bound_key},
        )

    assert other_service.status_code == status.HTTP_201_CREATED
    assert mismatched.status_code == status.HTTP_401_UNAUTHORIZED
    assert revoked.status_code == status.HTTP_401_UNAUTHORIZED
