"""Database-backed website uptime monitor API tests."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette import status

from watchtower.core.config import Settings
from watchtower.main import create_app
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import VIEWER_ROLE_ID
from watchtower.models.website_monitor import WebsiteMonitor
from watchtower.models.website_monitor_check import WebsiteMonitorCheck
from watchtower.schemas.auth import AuthenticatedUser

DATABASE_URL = os.environ["WATCHTOWER_DATABASE_URL"]
USERS = {
    token: AuthenticatedUser(id=uuid4(), username=f"uptime-{token}", is_admin=False)
    for token in ("owner", "viewer", "unrelated")
}


class UptimeAuthClient:
    async def get_current_user(self, token: str) -> AuthenticatedUser:
        return USERS[token]


@asynccontextmanager
async def uptime_client(
    *, max_active_monitors_per_profile: int = 100
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            auth_service_url="http://auth.test",
            uptime_max_active_monitors_per_profile=max_active_monitors_per_profile,
        )
    )
    app.state.auth_client = UptimeAuthClient()
    factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="https://watchtower.test",
        ) as client:
            try:
                yield client, factory
            finally:
                async with factory() as session:
                    async with session.begin():
                        profile_ids = select(Profile.id).where(
                            Profile.auth_user_id.in_([user.id for user in USERS.values()])
                        )
                        service_ids = select(MonitoredService.id).where(
                            MonitoredService.profile_id.in_(profile_ids)
                        )
                        await session.execute(
                            delete(WebsiteMonitor).where(WebsiteMonitor.service_id.in_(service_ids))
                        )
                        await session.execute(
                            delete(ProfileRole).where(
                                (ProfileRole.profile_id.in_(profile_ids))
                                | (ProfileRole.granted_by_profile_id.in_(profile_ids))
                            )
                        )
                        await session.execute(
                            delete(MonitoredService).where(
                                MonitoredService.profile_id.in_(profile_ids)
                            )
                        )
                        await session.execute(
                            delete(Profile).where(
                                Profile.auth_user_id.in_([user.id for user in USERS.values()])
                            )
                        )


def auth(token: str = "owner") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_service(client: AsyncClient) -> dict[str, object]:
    response = await client.post(
        "/api/v1/services",
        headers=auth(),
        json={
            "slug": f"uptime-{uuid4().hex}",
            "display_name": "Public website",
            "environment": "production",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, object], response.json())


async def test_create_and_list_monitor_requires_only_url_and_existing_service() -> None:
    async with uptime_client() as (client, _):
        service = await create_service(client)
        created = await client.post(
            "/api/v1/uptime-monitors",
            headers=auth(),
            json={"url": "HTTPS://Example.COM", "service_id": service["id"]},
        )
        listed = await client.get("/api/v1/uptime-monitors", headers=auth())

    assert created.status_code == status.HTTP_201_CREATED
    assert created.json() == {
        "id": created.json()["id"],
        "service_id": service["id"],
        "service_slug": service["slug"],
        "service_display_name": "Public website",
        "url": "https://example.com/",
        "active": True,
        "last_checked_at": None,
        "last_is_up": None,
        "last_status_code": None,
        "last_response_time_ms": None,
        "uptime_24h_percent": None,
        "created_at": created.json()["created_at"],
        "updated_at": created.json()["updated_at"],
    }
    assert listed.status_code == status.HTTP_200_OK
    assert listed.json() == [created.json()]


async def test_duplicate_is_conflict_and_delete_deactivates_monitor() -> None:
    async with uptime_client() as (client, factory):
        service = await create_service(client)
        payload = {"url": "https://example.org/health", "service_id": service["id"]}
        created = await client.post("/api/v1/uptime-monitors", headers=auth(), json=payload)
        duplicate = await client.post("/api/v1/uptime-monitors", headers=auth(), json=payload)
        async with factory() as session:
            async with session.begin():
                session.add(
                    WebsiteMonitorCheck(
                        monitor_id=created.json()["id"],
                        is_up=True,
                        status_code=200,
                        response_time_ms=10,
                    )
                )
        deleted = await client.delete(
            f"/api/v1/uptime-monitors/{created.json()['id']}", headers=auth()
        )
        listed = await client.get("/api/v1/uptime-monitors", headers=auth())
        recreated = await client.post(
            "/api/v1/uptime-monitors", headers=auth(), json=payload
        )

    assert created.status_code == status.HTTP_201_CREATED
    assert duplicate.status_code == status.HTTP_409_CONFLICT
    assert duplicate.json() == {"detail": "URL already monitored for service"}
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert listed.json() == []
    assert recreated.status_code == status.HTTP_201_CREATED
    assert recreated.json()["id"] == created.json()["id"]
    assert recreated.json()["active"] is True
    assert recreated.json()["uptime_24h_percent"] == 100.0


async def test_application_permissions_bound_visibility_and_management() -> None:
    async with uptime_client() as (client, factory):
        service = await create_service(client)
        created = await client.post(
            "/api/v1/uptime-monitors",
            headers=auth(),
            json={"url": "https://example.net/", "service_id": service["id"]},
        )
        for token in ("viewer", "unrelated"):
            response = await client.get("/api/v1/services", headers=auth(token))
            assert response.status_code == status.HTTP_200_OK

        async with factory() as session:
            async with session.begin():
                viewer_profile_id = await session.scalar(
                    select(Profile.id).where(Profile.auth_user_id == USERS["viewer"].id)
                )
                owner_profile_id = await session.scalar(
                    select(Profile.id).where(Profile.auth_user_id == USERS["owner"].id)
                )
                assert viewer_profile_id is not None
                assert owner_profile_id is not None
                session.add(
                    ProfileRole(
                        profile_id=viewer_profile_id,
                        role_id=VIEWER_ROLE_ID,
                        role_scope_kind="application",
                        application_id=service["id"],
                        granted_by_profile_id=owner_profile_id,
                    )
                )
                monitor_id = created.json()["id"]
                session.add_all(
                    [
                        WebsiteMonitorCheck(
                            monitor_id=monitor_id,
                            is_up=True,
                            status_code=200,
                            response_time_ms=10,
                        ),
                        WebsiteMonitorCheck(
                            monitor_id=monitor_id,
                            is_up=False,
                            status_code=503,
                            response_time_ms=20,
                            failure_kind="http",
                        ),
                    ]
                )

        viewer_list = await client.get("/api/v1/uptime-monitors", headers=auth("viewer"))
        unrelated_list = await client.get(
            "/api/v1/uptime-monitors", headers=auth("unrelated")
        )
        viewer_create = await client.post(
            "/api/v1/uptime-monitors",
            headers=auth("viewer"),
            json={"url": "https://example.net/other", "service_id": service["id"]},
        )
        viewer_delete = await client.delete(
            f"/api/v1/uptime-monitors/{created.json()['id']}", headers=auth("viewer")
        )

    assert viewer_list.status_code == status.HTTP_200_OK
    assert len(viewer_list.json()) == 1
    assert viewer_list.json()[0]["uptime_24h_percent"] == 50.0
    assert unrelated_list.status_code == status.HTTP_200_OK
    assert unrelated_list.json() == []
    for denied in (viewer_create, viewer_delete):
        assert denied.status_code == status.HTTP_403_FORBIDDEN
        assert denied.json() == {"detail": "Application access denied"}


async def test_profile_active_monitor_quota_bounds_recurring_probes() -> None:
    async with uptime_client(max_active_monitors_per_profile=1) as (client, _):
        service = await create_service(client)
        first = await client.post("/api/v1/uptime-monitors", headers=auth(), json={"url": "https://one.example/", "service_id": service["id"]})
        limited = await client.post("/api/v1/uptime-monitors", headers=auth(), json={"url": "https://two.example/", "service_id": service["id"]})
    assert first.status_code == status.HTTP_201_CREATED
    assert limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert limited.json() == {"detail": "Active website monitor limit reached"}
