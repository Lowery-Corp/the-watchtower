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
from watchtower.repositories.application_memberships import (
    application_membership_assignment_id,
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


async def provisioned_profile_ids(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    *tokens: str,
) -> dict[str, UUID]:
    for token in tokens:
        response = await client.get("/api/v1/services", headers=auth(token))
        assert response.status_code == status.HTTP_200_OK
    async with factory() as session:
        rows = (
            await session.execute(
                select(Profile.id, Profile.auth_user_id).where(
                    Profile.auth_user_id.in_([USERS[token].id for token in tokens])
                )
            )
        ).all()
    by_user = {auth_user_id: profile_id for profile_id, auth_user_id in rows}
    return {token: by_user[USERS[token].id] for token in tokens}


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
async def test_application_membership_permissions_bound_api_key_management() -> None:
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
    assert viewer_get.status_code == status.HTTP_403_FORBIDDEN
    assert viewer_get.json() == {"detail": "Application access denied"}


@pytest.mark.integration
async def test_api_key_rbac_cross_profile_creator_and_application_name_scope() -> None:
    async with service_client() as (client, factory):
        first = await client.post(
            "/api/v1/services", json=payload("Key RBAC first"), headers=auth("owner")
        )
        second = await client.post(
            "/api/v1/services", json=payload("Key RBAC second"), headers=auth("owner")
        )
        first_id = UUID(first.json()["id"])
        second_id = UUID(second.json()["id"])
        await assign_test_roles(client, factory, application_id=first_id)

        created_by_app_admin = await client.post(
            "/api/v1/api-keys",
            json={"name": "shared-name", "service_id": str(first_id)},
            headers=auth("app-admin"),
        )
        key_id = created_by_app_admin.json()["id"]
        same_application_conflict = await client.post(
            "/api/v1/api-keys",
            json={"name": "shared-name", "service_id": str(first_id)},
            headers=auth("owner"),
        )
        same_name_other_application = await client.post(
            "/api/v1/api-keys",
            json={"name": "shared-name", "service_id": str(second_id)},
            headers=auth("owner"),
        )
        app_admin_update = await client.patch(
            f"/api/v1/api-keys/{key_id}",
            json={"name": "app-admin-renamed"},
            headers=auth("app-admin"),
        )
        global_update = await client.patch(
            f"/api/v1/api-keys/{key_id}",
            json={"name": "global-renamed"},
            headers=auth("global-admin"),
        )
        viewer_update = await client.patch(
            f"/api/v1/api-keys/{key_id}",
            json={"name": "viewer-forbidden"},
            headers=auth("viewer"),
        )
        unrelated_get = await client.get(f"/api/v1/api-keys/{key_id}", headers=auth("unrelated"))
        owner_list = await client.get("/api/v1/api-keys", headers=auth("owner"))
        app_admin_list = await client.get("/api/v1/api-keys", headers=auth("app-admin"))
        viewer_list = await client.get("/api/v1/api-keys", headers=auth("viewer"))
        revoked = await client.delete(f"/api/v1/api-keys/{key_id}", headers=auth("app-admin"))

        async with factory() as session:
            creator_id = await session.scalar(
                select(Profile.id).where(Profile.auth_user_id == USERS["app-admin"].id)
            )
            persisted = await session.scalar(select(ApiKey).where(ApiKey.id == UUID(key_id)))

    assert created_by_app_admin.status_code == status.HTTP_201_CREATED
    assert created_by_app_admin.headers["Cache-Control"] == "no-store"
    assert same_application_conflict.status_code == status.HTTP_409_CONFLICT
    assert same_name_other_application.status_code == status.HTTP_201_CREATED
    assert app_admin_update.status_code == status.HTTP_200_OK
    assert global_update.status_code == status.HTTP_200_OK
    for denied in (viewer_update, unrelated_get):
        assert denied.status_code == status.HTTP_403_FORBIDDEN
        assert denied.json() == {"detail": "Application access denied"}
    assert {item["id"] for item in owner_list.json()} == {
        key_id,
        same_name_other_application.json()["id"],
    }
    assert {item["id"] for item in app_admin_list.json()} == {key_id}
    assert viewer_list.json() == []
    assert revoked.status_code == status.HTTP_204_NO_CONTENT
    assert persisted is not None
    assert persisted.profile_id == creator_id
    assert persisted.service_id == first_id
    assert persisted.revoked_at is not None


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

    membership_path = "/api/v1/services/{service_id}/memberships"
    member_path = "/api/v1/services/{service_id}/memberships/{profile_id}"
    assert paths[membership_path]["get"]["responses"]["403"]["description"] == (
        "Application access denied"
    )
    for method in ("put", "delete"):
        assert paths[member_path][method]["responses"]["403"]["description"] == (
            "Application access denied"
        )
    assert paths[member_path]["put"]["responses"]["409"]["description"] == (
        "Application must retain an app_admin"
    )
    assert paths[member_path]["delete"]["responses"]["409"]["description"] == (
        "Application must retain an app_admin"
    )


@pytest.mark.integration
async def test_creator_can_list_application_memberships() -> None:
    async with service_client() as (client, _factory):
        created = await client.post(
            "/api/v1/services",
            json=payload("Membership list"),
            headers=auth("owner"),
        )
        service_id = UUID(created.json()["id"])

        response = await client.get(
            f"/api/v1/services/{service_id}/memberships",
            headers=auth("owner"),
        )
        creator_membership = response.json()[0]
        unchanged = await client.put(
            f"/api/v1/services/{service_id}/memberships/{creator_membership['profile_id']}",
            json={"role": "app_admin"},
            headers=auth("owner"),
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [
        {
            "id": response.json()[0]["id"],
            "profile_id": response.json()[0]["profile_id"],
            "role": "app_admin",
            "granted_by_profile_id": response.json()[0]["profile_id"],
            "granted_at": response.json()[0]["granted_at"],
        }
    ]
    assert unchanged.status_code == status.HTTP_200_OK
    assert unchanged.json() == creator_membership


@pytest.mark.integration
async def test_application_admin_can_set_viewer_membership_with_grant_metadata() -> None:
    async with service_client() as (client, factory):
        created = await client.post(
            "/api/v1/services",
            json=payload("Membership set"),
            headers=auth("owner"),
        )
        service_id = UUID(created.json()["id"])
        await client.get("/api/v1/services", headers=auth("viewer"))
        async with factory() as session:
            owner_id = await session.scalar(
                select(Profile.id).where(Profile.auth_user_id == USERS["owner"].id)
            )
            viewer_id = await session.scalar(
                select(Profile.id).where(Profile.auth_user_id == USERS["viewer"].id)
            )
        assert owner_id is not None
        assert viewer_id is not None

        response = await client.put(
            f"/api/v1/services/{service_id}/memberships/{viewer_id}",
            json={"role": "viewer"},
            headers=auth("owner"),
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["profile_id"] == str(viewer_id)
    assert response.json()["role"] == "viewer"
    assert response.json()["granted_by_profile_id"] == str(owner_id)
    assert response.json()["granted_at"] is not None


@pytest.mark.integration
async def test_last_application_admin_cannot_remove_own_membership() -> None:
    async with service_client() as (client, factory):
        created = await client.post(
            "/api/v1/services",
            json=payload("Last admin"),
            headers=auth("owner"),
        )
        service_id = UUID(created.json()["id"])
        async with factory() as session:
            owner_id = await session.scalar(
                select(Profile.id).where(Profile.auth_user_id == USERS["owner"].id)
            )
        assert owner_id is not None

        response = await client.delete(
            f"/api/v1/services/{service_id}/memberships/{owner_id}",
            headers=auth("owner"),
        )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {"detail": "Application must retain an app_admin"}


@pytest.mark.integration
async def test_set_is_idempotent_and_normalizes_legacy_duplicate_roles() -> None:
    async with service_client() as (client, factory):
        created = await client.post(
            "/api/v1/services", json=payload("Normalize"), headers=auth("owner")
        )
        service_id = UUID(created.json()["id"])
        ids = await provisioned_profile_ids(client, factory, "owner", "viewer")
        url = f"/api/v1/services/{service_id}/memberships/{ids['viewer']}"
        first = await client.put(url, json={"role": "viewer"}, headers=auth("owner"))
        second = await client.put(url, json={"role": "viewer"}, headers=auth("owner"))
        assert first.json() == second.json()
        assert UUID(first.json()["id"]) == application_membership_assignment_id(
            application_id=service_id, profile_id=ids["viewer"], role="viewer"
        )
        async with factory() as session:
            async with session.begin():
                session.add(
                    ProfileRole(
                        profile_id=ids["viewer"],
                        role_id=APP_ADMIN_ROLE_ID,
                        role_scope_kind="application",
                        application_id=service_id,
                        granted_by_profile_id=ids["owner"],
                    )
                )
        normalized = await client.put(url, json={"role": "viewer"}, headers=auth("owner"))
        async with factory() as session:
            roles = list(
                await session.scalars(
                    select(ProfileRole.role_id).where(
                        ProfileRole.application_id == service_id,
                        ProfileRole.profile_id == ids["viewer"],
                    )
                )
            )

    assert normalized.status_code == status.HTTP_200_OK
    assert normalized.json() == first.json()
    assert roles == [VIEWER_ROLE_ID]


@pytest.mark.integration
async def test_two_admins_allow_demotion_and_removal_but_not_final_demotion() -> None:
    async with service_client() as (client, factory):
        created = await client.post(
            "/api/v1/services", json=payload("Two admins"), headers=auth("owner")
        )
        service_id = UUID(created.json()["id"])
        ids = await provisioned_profile_ids(client, factory, "owner", "app-admin")
        member_url = f"/api/v1/services/{service_id}/memberships/{ids['app-admin']}"
        promoted = await client.put(member_url, json={"role": "app_admin"}, headers=auth("owner"))
        demoted = await client.put(member_url, json={"role": "viewer"}, headers=auth("owner"))
        final_demotion = await client.put(
            f"/api/v1/services/{service_id}/memberships/{ids['owner']}",
            json={"role": "viewer"},
            headers=auth("owner"),
        )
        promoted_again = await client.put(
            member_url, json={"role": "app_admin"}, headers=auth("owner")
        )
        removed = await client.delete(member_url, headers=auth("owner"))

    assert promoted.status_code == status.HTTP_200_OK
    assert demoted.status_code == status.HTTP_200_OK
    assert demoted.json()["role"] == "viewer"
    assert final_demotion.status_code == status.HTTP_409_CONFLICT
    assert final_demotion.json() == {"detail": "Application must retain an app_admin"}
    assert promoted_again.status_code == status.HTTP_200_OK
    assert removed.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.integration
async def test_membership_authorization_validation_and_missing_resources_are_stable() -> None:
    async with service_client() as (client, factory):
        created = await client.post(
            "/api/v1/services", json=payload("Authorization"), headers=auth("owner")
        )
        service_id = UUID(created.json()["id"])
        ids = await provisioned_profile_ids(
            client, factory, "owner", "viewer", "unrelated", "global-admin"
        )
        await assign_test_roles(client, factory, application_id=service_id)
        global_list = await client.get(
            f"/api/v1/services/{service_id}/memberships", headers=auth("global-admin")
        )
        scoped_list = await client.get(
            f"/api/v1/services/{service_id}/memberships", headers=auth("app-admin")
        )
        denied = [
            await client.get(f"/api/v1/services/{service_id}/memberships", headers=auth(token))
            for token in ("viewer", "unrelated")
        ]
        missing_profile = await client.put(
            f"/api/v1/services/{service_id}/memberships/{uuid4()}",
            json={"role": "viewer"},
            headers=auth("owner"),
        )
        missing_application = await client.get(
            f"/api/v1/services/{uuid4()}/memberships", headers=auth("global-admin")
        )
        invalid = await client.put(
            f"/api/v1/services/{service_id}/memberships/{ids['unrelated']}",
            json={"role": "watchtower_admin"},
            headers=auth("owner"),
        )
        denied_mutations = [
            await client.put(
                f"/api/v1/services/{service_id}/memberships/{ids['unrelated']}",
                json={"role": "viewer"},
                headers=auth(token),
            )
            for token in ("viewer", "unrelated")
        ]

    assert global_list.status_code == status.HTTP_200_OK
    assert scoped_list.status_code == status.HTTP_200_OK
    for response in denied + denied_mutations:
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == {"detail": "Application access denied"}
    assert missing_profile.status_code == status.HTTP_404_NOT_FOUND
    assert missing_profile.json() == {"detail": "Profile not found"}
    assert missing_application.status_code == status.HTTP_404_NOT_FOUND
    assert missing_application.json() == {"detail": "Application not found"}
    assert invalid.status_code == 422


@pytest.mark.integration
async def test_concurrent_global_admin_removals_retain_one_local_admin() -> None:
    async with service_client() as (client, factory):
        created = await client.post(
            "/api/v1/services", json=payload("Concurrent admins"), headers=auth("owner")
        )
        service_id = UUID(created.json()["id"])
        ids = await provisioned_profile_ids(client, factory, "owner", "app-admin", "global-admin")
        await assign_test_roles(client, factory, application_id=service_id)
        responses = await asyncio.gather(
            client.delete(
                f"/api/v1/services/{service_id}/memberships/{ids['owner']}",
                headers=auth("global-admin"),
            ),
            client.delete(
                f"/api/v1/services/{service_id}/memberships/{ids['app-admin']}",
                headers=auth("global-admin"),
            ),
        )
        async with factory() as session:
            remaining = list(
                await session.scalars(
                    select(ProfileRole).where(
                        ProfileRole.application_id == service_id,
                        ProfileRole.role_id == APP_ADMIN_ROLE_ID,
                    )
                )
            )

    assert sorted(response.status_code for response in responses) == [204, 409]
    assert len(remaining) == 1


@pytest.mark.integration
async def test_deterministic_id_collision_rolls_back_and_isolates_other_application() -> None:
    async with service_client() as (client, factory):
        first = await client.post(
            "/api/v1/services", json=payload("Collision target"), headers=auth("owner")
        )
        second = await client.post(
            "/api/v1/services", json=payload("Collision source"), headers=auth("owner")
        )
        first_id = UUID(first.json()["id"])
        second_id = UUID(second.json()["id"])
        ids = await provisioned_profile_ids(client, factory, "owner", "viewer", "unrelated")
        target_url = f"/api/v1/services/{first_id}/memberships/{ids['viewer']}"
        existing = await client.put(target_url, json={"role": "viewer"}, headers=auth("owner"))
        collision_id = application_membership_assignment_id(
            application_id=first_id,
            profile_id=ids["viewer"],
            role="app_admin",
        )
        async with factory() as session:
            async with session.begin():
                session.add(
                    ProfileRole(
                        id=collision_id,
                        profile_id=ids["unrelated"],
                        role_id=VIEWER_ROLE_ID,
                        role_scope_kind="application",
                        application_id=second_id,
                        granted_by_profile_id=ids["owner"],
                    )
                )
        failed = await client.put(target_url, json={"role": "app_admin"}, headers=auth("owner"))
        async with factory() as session:
            first_roles = list(
                await session.scalars(
                    select(ProfileRole.role_id).where(
                        ProfileRole.application_id == first_id,
                        ProfileRole.profile_id == ids["viewer"],
                    )
                )
            )
            collision = await session.get(ProfileRole, collision_id)

    assert existing.status_code == status.HTTP_200_OK
    assert failed.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert first_roles == [VIEWER_ROLE_ID]
    assert collision is not None
    assert collision.application_id == second_id
