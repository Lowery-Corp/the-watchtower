"""API tests for external-auth sessions and lazy Watchtower profiles."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette import status

from watchtower.clients.auth_service import (
    AuthServiceProtocolError,
    AuthServiceRateLimited,
    AuthServiceUnauthorized,
    AuthServiceUnavailable,
)
from watchtower.core.config import Settings
from watchtower.main import create_app
from watchtower.models.api_key import ApiKey
from watchtower.models.event import Event
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.outbox_message import OutboxMessage
from watchtower.models.profile import Profile
from watchtower.schemas.auth import AuthenticatedSession, AuthenticatedUser

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)
AUTH_USER_ID = UUID("dc8805dd-a710-4bf2-8c11-75af04ea52ef")


class FakeAuthClient:
    """Controllable auth-service substitute that never records passwords in errors."""

    def __init__(self) -> None:
        self.login_error: Exception | None = None
        self.me_error: Exception | None = None
        self.logout_error: Exception | None = None
        self.me_tokens: list[str] = []
        self.logout_tokens: list[str] = []
        self.user = AuthenticatedUser(
            id=AUTH_USER_ID,
            username="watcher",
            is_admin=False,
        )

    async def login(self, *, email: str, password: str) -> AuthenticatedSession:
        assert email == "watcher@example.com"
        assert password == "integration-password"
        if self.login_error is not None:
            raise self.login_error
        return AuthenticatedSession(user=self.user, token=SecretStr("session-token"))

    async def get_current_user(self, token: str) -> AuthenticatedUser:
        assert token in {"session-token", "explicit-token"}
        self.me_tokens.append(token)
        if self.me_error is not None:
            raise self.me_error
        return self.user

    async def logout(self, token: str) -> None:
        self.logout_tokens.append(token)
        if self.logout_error is not None:
            raise self.logout_error


@asynccontextmanager
async def auth_client(
    fake: FakeAuthClient,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        auth_service_url="http://auth.test",
        session_cookie_secure=True,
        browser_allowed_origins={"https://watchtower.test"},
    )
    app = create_app(settings)
    app.state.auth_client = fake
    factory = cast(async_sessionmaker[AsyncSession], app.state.session_factory)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://watchtower.test") as client:
            try:
                yield client, factory
            finally:
                async with factory() as session:
                    async with session.begin():
                        profile_ids = select(Profile.id).where(Profile.auth_user_id == AUTH_USER_ID)
                        service_ids = select(MonitoredService.id).where(
                            MonitoredService.profile_id.in_(profile_ids)
                        )
                        event_ids = select(Event.id).where(Event.profile_id.in_(profile_ids))
                        await session.execute(
                            delete(OutboxMessage).where(
                                (OutboxMessage.profile_id.in_(profile_ids))
                                | (OutboxMessage.service_id.in_(service_ids))
                                | (OutboxMessage.event_id.in_(event_ids))
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
                            delete(Profile).where(Profile.auth_user_id == AUTH_USER_ID)
                        )


@pytest.mark.integration
async def test_login_sets_secure_http_only_cookie_without_returning_user_info() -> None:
    async with auth_client(FakeAuthClient()) as (client, factory):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "watcher@example.com",
                "password": "integration-password",
            },
        )
        async with factory() as session:
            profile = await session.scalar(
                select(Profile).where(Profile.auth_user_id == AUTH_USER_ID)
            )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert profile is not None
    assert profile.last_authenticated_at is not None
    assert response.content == b""
    assert "session-token" not in response.text
    cookie = response.headers["set-cookie"]
    assert "watchtower_session=session-token" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=3600" in cookie


@pytest.mark.integration
async def test_me_lazily_provisions_exactly_one_profile() -> None:
    async with auth_client(FakeAuthClient()) as (client, factory):
        client.cookies.set("watchtower_session", "session-token")
        first = await client.get("/api/v1/auth/me")
        second = await client.get("/api/v1/auth/me")
        async with factory() as session:
            profile_rows = list(
                (
                    await session.scalars(
                        Profile.__table__.select().where(Profile.auth_user_id == AUTH_USER_ID)
                    )
                ).all()
            )

    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_200_OK
    assert first.json()["profile_id"] == second.json()["profile_id"]
    assert first.json()["username"] == "watcher"
    assert len(profile_rows) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",
        "/api/v1/services",
        "/api/v1/api-keys",
    ],
)
async def test_suspended_profile_is_rejected_by_human_protected_paths(path: str) -> None:
    fake = FakeAuthClient()
    async with auth_client(fake) as (client, factory):
        async with factory() as session:
            async with session.begin():
                session.add(
                    Profile(
                        auth_user_id=AUTH_USER_ID,
                        display_name="Suspended watcher",
                        status="suspended",
                    )
                )
        response = await client.get(path, headers={"Authorization": "Bearer explicit-token"})
        async with factory() as session:
            persisted_status = await session.scalar(
                select(Profile.status).where(Profile.auth_user_id == AUTH_USER_ID)
            )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Profile access denied"}
    assert persisted_status == "suspended"


@pytest.mark.integration
async def test_suspended_profile_cannot_login_but_can_end_existing_session() -> None:
    fake = FakeAuthClient()
    async with auth_client(fake) as (client, factory):
        async with factory() as session:
            async with session.begin():
                session.add(
                    Profile(
                        auth_user_id=AUTH_USER_ID,
                        display_name="Suspended watcher",
                        status="suspended",
                    )
                )
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "watcher@example.com",
                "password": "integration-password",
            },
        )
        client.cookies.set("watchtower_session", "session-token")
        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://watchtower.test"},
        )

    assert login_response.status_code == status.HTTP_403_FORBIDDEN
    assert login_response.json() == {"detail": "Profile access denied"}
    assert "watchtower_session" not in login_response.headers.get("set-cookie", "")
    assert logout_response.status_code == status.HTTP_204_NO_CONTENT
    assert fake.logout_tokens == ["session-token", "session-token"]
    logout_cookie = logout_response.headers["set-cookie"]
    assert "watchtower_session=" in logout_cookie
    assert "Max-Age=0" in logout_cookie


@pytest.mark.integration
async def test_logout_clears_cookie_without_prevalidating_stale_session() -> None:
    fake = FakeAuthClient()
    fake.me_error = AuthServiceUnauthorized("expired session")
    fake.logout_error = AuthServiceUnauthorized("expired session")
    async with auth_client(fake) as (client, _):
        client.cookies.set("watchtower_session", "session-token")
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://watchtower.test"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert fake.me_tokens == []
    assert fake.logout_tokens == ["session-token"]
    cookie = response.headers["set-cookie"]
    assert "watchtower_session=" in cookie
    assert "Max-Age=0" in cookie


@pytest.mark.integration
async def test_profile_denial_is_documented_for_human_protected_routes() -> None:
    async with auth_client(FakeAuthClient()) as (client, _):
        response = await client.get("/api/v1/openapi.json")

    assert response.status_code == status.HTTP_200_OK
    paths = response.json()["paths"]
    protected_operations = [
        operation
        for path, path_item in paths.items()
        if path in {"/api/v1/auth/login", "/api/v1/auth/me"}
        or path.startswith(("/api/v1/services", "/api/v1/api-keys"))
        for method, operation in path_item.items()
        if method in {"get", "post", "patch", "delete", "put"}
    ]
    assert protected_operations
    assert all("403" in operation["responses"] for operation in protected_operations)


@pytest.mark.integration
async def test_missing_session_is_unauthorized() -> None:
    async with auth_client(FakeAuthClient()) as (client, _):
        response = await client.get("/api/v1/auth/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",
        "/api/v1/services",
        f"/api/v1/services/{uuid4()}",
        "/api/v1/api-keys",
        f"/api/v1/api-keys/{uuid4()}",
    ],
)
async def test_every_user_information_route_rejects_anonymous_access(path: str) -> None:
    async with auth_client(FakeAuthClient()) as (client, _):
        response = await client.get(path)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.integration
async def test_explicit_bearer_precedes_cookie_and_malformed_header_does_not_fallback() -> None:
    fake = FakeAuthClient()
    async with auth_client(fake) as (client, _):
        client.cookies.set("watchtower_session", "session-token")
        explicit = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer explicit-token"},
        )
        malformed = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "NotBearer explicit-token"},
        )

    assert explicit.status_code == status.HTTP_200_OK
    assert malformed.status_code == status.HTTP_401_UNAUTHORIZED
    assert fake.me_tokens == ["explicit-token"]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (AuthServiceUnauthorized("private upstream detail"), 401),
        (AuthServiceProtocolError("private upstream detail"), 502),
        (AuthServiceUnavailable("private upstream detail"), 503),
        (AuthServiceRateLimited(17), 429),
    ],
)
async def test_login_maps_auth_failures_generically(
    error: Exception,
    expected_status: int,
) -> None:
    fake = FakeAuthClient()
    fake.login_error = error
    async with auth_client(fake) as (client, _):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "watcher@example.com",
                "password": "integration-password",
            },
        )

    assert response.status_code == expected_status
    assert "private upstream detail" not in response.text


@pytest.mark.integration
async def test_cookie_authenticated_mutation_requires_trusted_origin() -> None:
    fake = FakeAuthClient()
    async with auth_client(fake) as (client, _):
        client.cookies.set("watchtower_session", "session-token")
        rejected = await client.post(
            "/api/v1/api-keys",
            json={"name": "csrf-rejected"},
        )
        accepted = await client.post(
            "/api/v1/api-keys",
            json={"name": "csrf-accepted"},
            headers={"Origin": "https://watchtower.test"},
        )

    assert rejected.status_code == status.HTTP_403_FORBIDDEN
    assert accepted.status_code == status.HTTP_201_CREATED


@pytest.mark.integration
async def test_logout_clears_cookie_and_attempts_upstream_invalidation() -> None:
    fake = FakeAuthClient()
    async with auth_client(fake) as (client, _):
        client.cookies.set("watchtower_session", "session-token")
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://watchtower.test"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert fake.logout_tokens == ["session-token"]
    cookie = response.headers["set-cookie"]
    assert "watchtower_session=" in cookie
    assert "Max-Age=0" in cookie


@pytest.mark.integration
async def test_logout_outage_is_reported_but_cookie_is_still_cleared() -> None:
    fake = FakeAuthClient()
    fake.logout_error = AuthServiceUnavailable("private upstream detail")
    async with auth_client(fake) as (client, _):
        client.cookies.set("watchtower_session", "session-token")
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://watchtower.test"},
        )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "private upstream detail" not in response.text
    cookie = response.headers["set-cookie"]
    assert "watchtower_session=" in cookie
    assert "Max-Age=0" in cookie
