"""Database-backed monitored-service authorization API tests."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette import status

from watchtower.core.config import Settings
from watchtower.main import create_app
from watchtower.models.api_key import ApiKey
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import (
    APP_ADMIN_ROLE_ID,
    VIEWER_ROLE_ID,
    WATCHTOWER_ADMIN_ROLE_ID,
)
from watchtower.schemas.auth import AuthenticatedUser

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)
USERS = {
    token: AuthenticatedUser(id=uuid4(), username=name, is_admin=False)
    for token, name in (
        ("owner", "owner"),
        ("app-admin", "app-admin"),
        ("viewer", "viewer"),
        ("unrelated", "unrelated"),
        ("global-admin", "global-admin"),
    )
}


class RoleAuthClient:
    async def get_current_user(self, token: str) -> AuthenticatedUser:
        return USERS[token]


@asynccontextmanager
async def service_client() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            auth_service_url="http://auth.test",
        )
    )
    app.state.auth_client = RoleAuthClient()
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
                            Profile.auth_user_id.in_([user.id for user in USERS.values()])
                        )
                        await session.execute(
                            delete(ApiKey).where(ApiKey.profile_id.in_(profile_ids))
                        )
                        await session.execute(
                            delete(ProfileRole).where(
                                or_(
                                    ProfileRole.profile_id.in_(profile_ids),
                                    ProfileRole.granted_by_profile_id.in_(profile_ids),
                                )
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def payload(name: str) -> dict[str, str]:
    slug_name = name.lower().replace(" ", "-")
    return {
        "slug": f"{slug_name}-{uuid4().hex}",
        "display_name": name,
        "environment": "test",
    }


async def assign_test_roles(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    *,
    application_id: UUID,
) -> None:
    """Provision test profiles, then grant explicit PostgreSQL role rows."""

    for token in ("app-admin", "viewer", "unrelated", "global-admin"):
        response = await client.get("/api/v1/services", headers=auth(token))
        assert response.status_code == status.HTTP_200_OK

    async with factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    select(Profile.id, Profile.auth_user_id).where(
                        Profile.auth_user_id.in_([user.id for user in USERS.values()])
                    )
                )
            ).all()
            profile_by_user = {auth_user_id: profile_id for profile_id, auth_user_id in rows}
            owner_id = profile_by_user[USERS["owner"].id]
            session.add_all(
                [
                    ProfileRole(
                        profile_id=profile_by_user[USERS["app-admin"].id],
                        role_id=APP_ADMIN_ROLE_ID,
                        role_scope_kind="application",
                        application_id=application_id,
                        granted_by_profile_id=owner_id,
                    ),
                    ProfileRole(
                        profile_id=profile_by_user[USERS["viewer"].id],
                        role_id=VIEWER_ROLE_ID,
                        role_scope_kind="application",
                        application_id=application_id,
                        granted_by_profile_id=owner_id,
                    ),
                    ProfileRole(
                        profile_id=profile_by_user[USERS["global-admin"].id],
                        role_id=WATCHTOWER_ADMIN_ROLE_ID,
                        role_scope_kind="global",
                        granted_by_profile_id=profile_by_user[USERS["global-admin"].id],
                    ),
                ]
            )


@pytest.mark.integration
async def test_every_active_profile_can_create_and_receives_application_access() -> None:
    async with service_client() as (client, factory):
        created = await client.post(
            "/api/v1/services", json=payload("Creator application"), headers=auth("owner")
        )
        service_id = UUID(created.json()["id"])
        fetched = await client.get(f"/api/v1/services/{service_id}", headers=auth("owner"))
        updated = await client.patch(
            f"/api/v1/services/{service_id}",
            json={"display_name": "Updated by creator"},
            headers=auth("owner"),
        )
        async with factory() as session:
            assignment = await session.scalar(
                select(ProfileRole).where(ProfileRole.application_id == service_id)
            )

    assert created.status_code == status.HTTP_201_CREATED
    assert fetched.status_code == status.HTTP_200_OK
    assert updated.status_code == status.HTTP_200_OK
    assert assignment is not None
    assert assignment.role_id == APP_ADMIN_ROLE_ID
    assert assignment.granted_by_profile_id == assignment.profile_id


@pytest.mark.integration
async def test_concurrent_duplicate_creation_commits_one_owned_application() -> None:
    duplicate_payload = payload("Concurrent")
    async with service_client() as (client, factory):
        responses = await asyncio.gather(
            client.post(
                "/api/v1/services",
                json=duplicate_payload,
                headers=auth("owner"),
            ),
            client.post(
                "/api/v1/services",
                json=duplicate_payload,
                headers=auth("owner"),
            ),
        )
        async with factory() as session:
            services = list(
                await session.scalars(
                    select(MonitoredService).where(
                        MonitoredService.slug == duplicate_payload["slug"]
                    )
                )
            )
            assignments = list(
                await session.scalars(
                    select(ProfileRole).where(
                        ProfileRole.application_id.in_([service.id for service in services])
                    )
                )
            )

    assert sorted(response.status_code for response in responses) == [
        status.HTTP_201_CREATED,
        status.HTTP_409_CONFLICT,
    ]
    assert len(services) == 1
    assert len(assignments) == 1
    assert assignments[0].role_id == APP_ADMIN_ROLE_ID


@pytest.mark.integration
async def test_application_roles_enforce_list_read_and_manage_boundaries() -> None:
    async with service_client() as (client, factory):
        first = await client.post("/api/v1/services", json=payload("First"), headers=auth("owner"))
        second = await client.post(
            "/api/v1/services", json=payload("Second"), headers=auth("owner")
        )
        first_id = UUID(first.json()["id"])
        second_id = UUID(second.json()["id"])
        await assign_test_roles(client, factory, application_id=first_id)

        lists = {
            token: await client.get("/api/v1/services", headers=auth(token))
            for token in ("owner", "app-admin", "viewer", "unrelated", "global-admin")
        }
        async with factory() as session:
            all_application_ids = set(await session.scalars(select(MonitoredService.id)))
        app_admin_read = await client.get(f"/api/v1/services/{first_id}", headers=auth("app-admin"))
        viewer_read = await client.get(f"/api/v1/services/{first_id}", headers=auth("viewer"))
        unrelated_read = await client.get(f"/api/v1/services/{first_id}", headers=auth("unrelated"))
        wrong_application = await client.get(
            f"/api/v1/services/{second_id}", headers=auth("app-admin")
        )
        app_admin_update = await client.patch(
            f"/api/v1/services/{first_id}",
            json={"display_name": "Managed"},
            headers=auth("app-admin"),
        )
        viewer_update = await client.patch(
            f"/api/v1/services/{first_id}",
            json={"display_name": "Forbidden"},
            headers=auth("viewer"),
        )
        unrelated_update = await client.patch(
            f"/api/v1/services/{first_id}",
            json={"display_name": "Forbidden"},
            headers=auth("unrelated"),
        )
        global_update = await client.patch(
            f"/api/v1/services/{second_id}",
            json={"display_name": "Globally managed"},
            headers=auth("global-admin"),
        )
        viewer_deactivate = await client.delete(
            f"/api/v1/services/{first_id}", headers=auth("viewer")
        )
        app_admin_deactivate = await client.delete(
            f"/api/v1/services/{first_id}", headers=auth("app-admin")
        )
        global_activate = await client.patch(
            f"/api/v1/services/{first_id}",
            json={"active": True},
            headers=auth("global-admin"),
        )

    assert {item["id"] for item in lists["owner"].json()} == {str(first_id), str(second_id)}
    assert {item["id"] for item in lists["app-admin"].json()} == {str(first_id)}
    assert {item["id"] for item in lists["viewer"].json()} == {str(first_id)}
    assert lists["unrelated"].json() == []
    assert {UUID(item["id"]) for item in lists["global-admin"].json()} == all_application_ids
    assert app_admin_read.status_code == status.HTTP_200_OK
    assert viewer_read.status_code == status.HTTP_200_OK
    for denied in (
        unrelated_read,
        wrong_application,
        viewer_update,
        unrelated_update,
        viewer_deactivate,
    ):
        assert denied.status_code == status.HTTP_403_FORBIDDEN
        assert denied.json() == {"detail": "Application access denied"}
    assert app_admin_update.status_code == status.HTTP_200_OK
    assert global_update.status_code == status.HTTP_200_OK
    assert app_admin_deactivate.status_code == status.HTTP_204_NO_CONTENT
    assert global_activate.status_code == status.HTTP_200_OK
    assert global_activate.json()["active"] is True


@pytest.mark.integration
async def test_application_membership_does_not_authorize_api_key_management() -> None:
    async with service_client() as (client, factory):
        service = await client.post(
            "/api/v1/services", json=payload("Key boundary"), headers=auth("owner")
        )
        service_id = UUID(service.json()["id"])
        await assign_test_roles(client, factory, application_id=service_id)
        key = await client.post(
            "/api/v1/api-keys",
            json={"name": "Owner key", "service_id": str(service_id)},
            headers=auth("owner"),
        )
        viewer_list = await client.get("/api/v1/api-keys", headers=auth("viewer"))
        viewer_get = await client.get(
            f"/api/v1/api-keys/{key.json()['id']}", headers=auth("viewer")
        )

    assert key.status_code == status.HTTP_201_CREATED
    assert viewer_list.status_code == status.HTTP_200_OK
    assert viewer_list.json() == []
    assert viewer_get.status_code == status.HTTP_404_NOT_FOUND


def test_application_openapi_documents_forbidden_responses() -> None:
    schema = create_app(Settings(environment="test", auth_service_url="http://auth.test")).openapi()
    paths = schema["paths"]

    for path, method in (
        ("/api/v1/services", "get"),
        ("/api/v1/services/{service_id}", "get"),
        ("/api/v1/services/{service_id}", "patch"),
        ("/api/v1/services/{service_id}", "delete"),
    ):
        assert paths[path][method]["responses"]["403"]["description"] == (
            "Application access denied"
        )
