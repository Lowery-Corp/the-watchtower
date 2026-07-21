"""Profile-scoped monitored-service API tests."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette import status

from watchtower.core.config import Settings
from watchtower.main import create_app
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.schemas.auth import AuthenticatedUser

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)
USER_A = AuthenticatedUser(id=uuid4(), username="tenant-a", is_admin=False)
USER_B = AuthenticatedUser(id=uuid4(), username="tenant-b", is_admin=False)


class TenantAuthClient:
    async def get_current_user(self, token: str) -> AuthenticatedUser:
        return {"token-a": USER_A, "token-b": USER_B}[token]


@asynccontextmanager
async def service_client() -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            auth_service_url="http://auth.test",
        )
    )
    app.state.auth_client = TenantAuthClient()
    factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://watchtower.test") as client:
            try:
                yield client
            finally:
                async with factory() as session:
                    async with session.begin():
                        profile_ids = select(Profile.id).where(
                            Profile.auth_user_id.in_([USER_A.id, USER_B.id])
                        )
                        await session.execute(
                            delete(MonitoredService).where(
                                MonitoredService.profile_id.in_(profile_ids)
                            )
                        )
                        await session.execute(
                            delete(Profile).where(
                                Profile.auth_user_id.in_([USER_A.id, USER_B.id])
                            )
                        )


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_services_are_siloed_and_slugs_are_unique_per_profile() -> None:
    slug = f"shared-{uuid4().hex}"
    payload = {
        "slug": slug,
        "display_name": "Shared service",
        "environment": "test",
    }
    async with service_client() as client:
        created_a = await client.post("/api/v1/services", json=payload, headers=auth("token-a"))
        created_b = await client.post("/api/v1/services", json=payload, headers=auth("token-b"))
        duplicate_a = await client.post(
            "/api/v1/services", json=payload, headers=auth("token-a")
        )
        list_a = await client.get("/api/v1/services", headers=auth("token-a"))
        list_b = await client.get("/api/v1/services", headers=auth("token-b"))
        hidden = await client.get(
            f"/api/v1/services/{created_a.json()['id']}", headers=auth("token-b")
        )

    assert created_a.status_code == status.HTTP_201_CREATED
    assert created_b.status_code == status.HTTP_201_CREATED
    assert created_a.json()["id"] != created_b.json()["id"]
    assert "secret_key_id" not in created_a.json()
    assert duplicate_a.status_code == status.HTTP_409_CONFLICT
    assert [item["id"] for item in list_a.json()] == [created_a.json()["id"]]
    assert [item["id"] for item in list_b.json()] == [created_b.json()["id"]]
    assert hidden.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
async def test_service_owner_can_update_and_deactivate_service() -> None:
    payload = {
        "slug": f"service-{uuid4().hex}",
        "display_name": "Before",
        "environment": "test",
    }
    async with service_client() as client:
        created = await client.post("/api/v1/services", json=payload, headers=auth("token-a"))
        service_id = UUID(created.json()["id"])
        updated = await client.patch(
            f"/api/v1/services/{service_id}",
            json={"display_name": "After"},
            headers=auth("token-a"),
        )
        deleted = await client.delete(
            f"/api/v1/services/{service_id}", headers=auth("token-a")
        )
        fetched = await client.get(
            f"/api/v1/services/{service_id}", headers=auth("token-a")
        )

    assert updated.status_code == status.HTTP_200_OK
    assert updated.json()["display_name"] == "After"
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert fetched.status_code == status.HTTP_200_OK
    assert fetched.json()["active"] is False
