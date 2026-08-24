"""Profile-owned API-key lifecycle tests."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette import status

from watchtower.core.config import Settings
from watchtower.main import create_app
from watchtower.models.api_key import ApiKey
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.models.profile_role import ProfileRole
from watchtower.schemas.auth import AuthenticatedUser

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)
USER_A = AuthenticatedUser(id=uuid4(), username="key-owner-a", is_admin=False)
USER_B = AuthenticatedUser(id=uuid4(), username="key-owner-b", is_admin=False)


class KeyAuthClient:
    async def get_current_user(self, token: str) -> AuthenticatedUser:
        return {"token-a": USER_A, "token-b": USER_B}[token]


@asynccontextmanager
async def key_client() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            auth_service_url="http://auth.test",
        )
    )
    app.state.auth_client = KeyAuthClient()
    factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://watchtower.test") as client:
            try:
                yield client, factory
            finally:
                async with factory() as session:
                    async with session.begin():
                        profile_ids = select(Profile.id).where(
                            Profile.auth_user_id.in_([USER_A.id, USER_B.id])
                        )
                        await session.execute(
                            delete(ApiKey).where(ApiKey.profile_id.in_(profile_ids))
                        )
                        await session.execute(
                            delete(ProfileRole).where(ProfileRole.profile_id.in_(profile_ids))
                        )
                        await session.execute(
                            delete(MonitoredService).where(
                                MonitoredService.profile_id.in_(profile_ids)
                            )
                        )
                        await session.execute(
                            delete(Profile).where(Profile.auth_user_id.in_([USER_A.id, USER_B.id]))
                        )


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_key_plaintext_is_returned_once_and_digest_only_is_persisted() -> None:
    async with key_client() as (client, factory):
        created = await client.post(
            "/api/v1/api-keys",
            json={"name": "primary"},
            headers=auth("token-a"),
        )
        listed = await client.get("/api/v1/api-keys", headers=auth("token-a"))
        token = created.json()["api_key"]
        key_id = created.json()["id"]
        async with factory() as session:
            persisted = await session.scalar(select(ApiKey).where(ApiKey.id == key_id))

    assert created.status_code == status.HTTP_201_CREATED
    assert created.headers["Cache-Control"] == "no-store"
    assert token.startswith("wtk_v1_")
    assert created.json()["scopes"] == ["events:write"]
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == key_id
    assert "api_key" not in listed.json()[0]
    assert "secret_digest" not in listed.json()[0]
    assert persisted is not None
    assert persisted.secret_digest != token.encode()
    assert token.encode() not in persisted.secret_digest


@pytest.mark.integration
async def test_keys_are_siloed_and_cross_tenant_ids_return_not_found() -> None:
    async with key_client() as (client, _):
        created = await client.post(
            "/api/v1/api-keys",
            json={"name": "tenant-a-key"},
            headers=auth("token-a"),
        )
        key_id = created.json()["id"]
        list_b = await client.get("/api/v1/api-keys", headers=auth("token-b"))
        hidden = await client.get(f"/api/v1/api-keys/{key_id}", headers=auth("token-b"))

    assert list_b.status_code == status.HTTP_200_OK
    assert list_b.json() == []
    assert hidden.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
async def test_key_can_be_bound_to_owned_service_and_revoked() -> None:
    async with key_client() as (client, _):
        service = await client.post(
            "/api/v1/services",
            json={
                "slug": f"key-service-{uuid4().hex}",
                "display_name": "Key service",
                "environment": "test",
            },
            headers=auth("token-a"),
        )
        created = await client.post(
            "/api/v1/api-keys",
            json={"name": "service-key", "service_id": service.json()["id"]},
            headers=auth("token-a"),
        )
        key_id = created.json()["id"]
        revoked = await client.delete(f"/api/v1/api-keys/{key_id}", headers=auth("token-a"))
        fetched = await client.get(f"/api/v1/api-keys/{key_id}", headers=auth("token-a"))

    assert created.status_code == status.HTTP_201_CREATED
    assert created.json()["service_id"] == service.json()["id"]
    assert revoked.status_code == status.HTTP_204_NO_CONTENT
    assert fetched.status_code == status.HTTP_200_OK
    assert fetched.json()["revoked_at"] is not None


@pytest.mark.integration
async def test_key_expiry_must_be_in_the_future() -> None:
    async with key_client() as (client, _):
        response = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "expired",
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
            headers=auth("token-a"),
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
async def test_binding_is_immutable_and_expiry_cannot_be_extended_or_removed() -> None:
    initial_expiry = datetime.now(UTC) + timedelta(days=1)
    async with key_client() as (client, _):
        created = await client.post(
            "/api/v1/api-keys",
            json={"name": "restricted", "expires_at": initial_expiry.isoformat()},
            headers=auth("token-a"),
        )
        key_id = created.json()["id"]
        service = await client.post(
            "/api/v1/services",
            json={
                "slug": f"immutable-binding-{uuid4().hex}",
                "display_name": "Immutable binding",
                "environment": "test",
            },
            headers=auth("token-a"),
        )
        bind_after_creation = await client.patch(
            f"/api/v1/api-keys/{key_id}",
            json={"service_id": service.json()["id"]},
            headers=auth("token-a"),
        )
        extend_expiry = await client.patch(
            f"/api/v1/api-keys/{key_id}",
            json={"expires_at": (initial_expiry + timedelta(days=1)).isoformat()},
            headers=auth("token-a"),
        )
        remove_expiry = await client.patch(
            f"/api/v1/api-keys/{key_id}",
            json={"expires_at": None},
            headers=auth("token-a"),
        )
        rename = await client.patch(
            f"/api/v1/api-keys/{key_id}",
            json={"name": "restricted-renamed"},
            headers=auth("token-a"),
        )

    assert bind_after_creation.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert extend_expiry.status_code == status.HTTP_409_CONFLICT
    assert remove_expiry.status_code == status.HTTP_409_CONFLICT
    assert rename.status_code == status.HTTP_200_OK
    assert rename.json()["name"] == "restricted-renamed"
