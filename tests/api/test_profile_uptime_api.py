"""Database-backed machine-facing profile uptime API tests."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

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
from watchtower.models.role import VIEWER_ROLE_ID
from watchtower.models.webhook_rate_limit import WebhookRateLimit
from watchtower.models.website_monitor import WebsiteMonitor
from watchtower.models.website_monitor_check import WebsiteMonitorCheck
from watchtower.schemas.auth import AuthenticatedUser

DATABASE_URL = os.environ["WATCHTOWER_DATABASE_URL"]
USERS = {
    token: AuthenticatedUser(id=uuid4(), username=f"profile-uptime-{token}", is_admin=False)
    for token in ("reader", "other")
}


class ProfileUptimeAuthClient:
    async def get_current_user(self, token: str) -> AuthenticatedUser:
        return USERS[token]


@asynccontextmanager
async def profile_uptime_client(
    *, rate_limit_requests: int = 60
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            auth_service_url="http://auth.test",
            uptime_api_rate_limit_requests=rate_limit_requests,
            uptime_api_rate_limit_window_seconds=60,
        )
    )
    app.state.auth_client = ProfileUptimeAuthClient()
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
                        profile_ids = list(
                            await session.scalars(
                                select(Profile.id).where(
                                    Profile.auth_user_id.in_([user.id for user in USERS.values()])
                                )
                            )
                        )
                        service_ids = select(MonitoredService.id).where(
                            MonitoredService.profile_id.in_(profile_ids)
                        )
                        key_ids = list(
                            await session.scalars(
                                select(ApiKey.id).where(ApiKey.profile_id.in_(profile_ids))
                            )
                        )
                        await session.execute(
                            delete(WebsiteMonitor).where(WebsiteMonitor.service_id.in_(service_ids))
                        )
                        if key_ids:
                            await session.execute(
                                delete(WebhookRateLimit).where(
                                    WebhookRateLimit.identity.in_(
                                        [f"profile-uptime:{key_id}" for key_id in key_ids]
                                    )
                                )
                            )
                        await session.execute(
                            delete(ApiKey).where(ApiKey.profile_id.in_(profile_ids))
                        )
                        await session.execute(
                            delete(ProfileRole).where(
                                (ProfileRole.profile_id.in_(profile_ids))
                                | (ProfileRole.granted_by_profile_id.in_(profile_ids))
                            )
                        )
                        await session.execute(
                            delete(MonitoredService).where(MonitoredService.profile_id.in_(profile_ids))
                        )
                        await session.execute(delete(Profile).where(Profile.id.in_(profile_ids)))


def browser_auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_service(client: AsyncClient, token: str, label: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/services",
        headers=browser_auth(token),
        json={
            "slug": f"{label.lower().replace(' ', '-')}-{uuid4().hex}",
            "display_name": label,
            "environment": "production",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, object], response.json())


async def issue_profile_key(client: AsyncClient, token: str = "reader") -> str:
    response = await client.post(
        "/api/v1/api-keys",
        headers=browser_auth(token),
        json={"credential_kind": "profile_uptime"},
    )
    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
    return cast(str, response.json()["api_key"])


async def profile_id_for(
    factory: async_sessionmaker[AsyncSession], token: str
) -> UUID:
    async with factory() as session:
        profile_id = await session.scalar(
            select(Profile.id).where(Profile.auth_user_id == USERS[token].id)
        )
    assert profile_id is not None
    return profile_id


async def test_uptime_returns_all_and_only_readable_services_with_active_monitor_rollups() -> None:
    async with profile_uptime_client() as (client, factory):
        owned = await create_service(client, "reader", "Owned")
        empty = await create_service(client, "reader", "No monitors")
        unrelated = await create_service(client, "other", "Unrelated")
        shared = await create_service(client, "other", "Shared")
        token = await issue_profile_key(client)
        reader_id = await profile_id_for(factory, "reader")
        other_id = await profile_id_for(factory, "other")
        now = datetime.now(UTC)

        async with factory() as session:
            async with session.begin():
                session.add(
                    ProfileRole(
                        profile_id=reader_id,
                        role_id=VIEWER_ROLE_ID,
                        role_scope_kind="application",
                        application_id=shared["id"],
                        granted_by_profile_id=other_id,
                    )
                )
                pending = WebsiteMonitor(
                    service_id=owned["id"], url="https://pending.example/", created_at=now
                )
                up = WebsiteMonitor(
                    service_id=owned["id"],
                    url="https://up.example/",
                    last_checked_at=now - timedelta(seconds=5),
                    last_is_up=True,
                    last_status_code=200,
                    last_response_time_ms=84,
                    created_at=now + timedelta(seconds=1),
                )
                down = WebsiteMonitor(
                    service_id=shared["id"],
                    url="https://down.example/",
                    last_checked_at=now - timedelta(seconds=4),
                    last_is_up=False,
                    last_status_code=503,
                    last_response_time_ms=121,
                    created_at=now + timedelta(seconds=2),
                )
                inactive = WebsiteMonitor(
                    service_id=owned["id"],
                    url="https://inactive.example/",
                    active=False,
                    created_at=now + timedelta(seconds=3),
                )
                session.add_all([pending, up, down, inactive])
                await session.flush()
                session.add_all(
                    [
                        WebsiteMonitorCheck(
                            monitor_id=up.id,
                            checked_at=now - timedelta(hours=2),
                            is_up=True,
                            status_code=200,
                            response_time_ms=80,
                        ),
                        WebsiteMonitorCheck(
                            monitor_id=up.id,
                            checked_at=now - timedelta(hours=1),
                            is_up=True,
                            status_code=200,
                            response_time_ms=82,
                        ),
                        WebsiteMonitorCheck(
                            monitor_id=up.id,
                            checked_at=now - timedelta(minutes=30),
                            is_up=False,
                            status_code=503,
                            response_time_ms=100,
                        ),
                        WebsiteMonitorCheck(
                            monitor_id=up.id,
                            checked_at=now - timedelta(hours=25),
                            is_up=False,
                            status_code=503,
                            response_time_ms=100,
                        ),
                        WebsiteMonitorCheck(
                            monitor_id=up.id,
                            checked_at=now + timedelta(hours=1),
                            is_up=True,
                            status_code=200,
                            response_time_ms=79,
                        ),
                    ]
                )

        before = datetime.now(UTC)
        response = await client.get(
            "/api/v1/uptime", headers={"X-Watchtower-Profile-Key": token}
        )
        after = datetime.now(UTC)
        async with factory() as session:
            key = await session.scalar(
                select(ApiKey).where(
                    ApiKey.profile_id == reader_id,
                    ApiKey.credential_kind == "profile_uptime",
                )
            )

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["profile"] == {"id": str(reader_id)}
    assert before <= datetime.fromisoformat(body["generated_at"]) <= after
    assert [service["id"] for service in body["services"]] == [
        owned["id"], empty["id"], shared["id"]
    ]
    assert unrelated["id"] not in {service["id"] for service in body["services"]}
    assert body["services"][1]["monitors"] == []
    assert body["services"][0]["monitors"] == [
        {
            "id": str(pending.id),
            "url": "https://pending.example/",
            "status": "pending",
            "last_checked_at": None,
            "status_code": None,
            "response_time_ms": None,
            "uptime_24h_percent": None,
        },
        {
            "id": str(up.id),
            "url": "https://up.example/",
            "status": "up",
            "last_checked_at": (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
            "status_code": 200,
            "response_time_ms": 84,
            "uptime_24h_percent": 66.67,
        },
    ]
    assert body["services"][2]["monitors"][0]["status"] == "down"
    assert body["services"][2]["monitors"][0]["uptime_24h_percent"] is None
    assert key is not None
    assert key.last_used_at is not None
    assert before <= key.last_used_at <= after


async def test_missing_duplicate_malformed_unknown_and_superseded_keys_share_one_401() -> None:
    async with profile_uptime_client() as (client, _):
        old_token = await issue_profile_key(client)
        replacement_token = await issue_profile_key(client)
        unknown_token = (
            "wtp_v1_bbbbbbbbbbbbbbbb."
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        responses = [
            await client.get("/api/v1/uptime"),
            await client.get(
                "/api/v1/uptime",
                headers=[
                    ("X-Watchtower-Profile-Key", replacement_token),
                    ("X-Watchtower-Profile-Key", replacement_token),
                ],
            ),
            await client.get(
                "/api/v1/uptime",
                headers={"X-Watchtower-Profile-Key": " wtp_v1_invalid "},
            ),
            await client.get(
                "/api/v1/uptime",
                headers={"X-Watchtower-Profile-Key": unknown_token},
            ),
            await client.get(
                "/api/v1/uptime",
                headers={"X-Watchtower-Profile-Key": old_token},
            ),
        ]
        replacement = await client.get(
            "/api/v1/uptime",
            headers={"X-Watchtower-Profile-Key": replacement_token},
        )

    assert {(response.status_code, str(response.json())) for response in responses} == {
        (
            status.HTTP_401_UNAUTHORIZED,
            str({"detail": "Invalid profile uptime authentication"}),
        )
    }
    assert replacement.status_code == status.HTTP_200_OK


async def test_valid_key_for_suspended_profile_is_forbidden() -> None:
    async with profile_uptime_client() as (client, factory):
        token = await issue_profile_key(client)
        reader_id = await profile_id_for(factory, "reader")
        async with factory() as session:
            async with session.begin():
                profile = await session.get(Profile, reader_id, with_for_update=True)
                assert profile is not None
                profile.status = "suspended"
        response = await client.get(
            "/api/v1/uptime",
            headers={"X-Watchtower-Profile-Key": token},
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Profile is suspended"}


async def test_profile_key_rate_limit_persists_and_does_not_record_rejected_use() -> None:
    async with profile_uptime_client(rate_limit_requests=1) as (client, factory):
        token = await issue_profile_key(client)
        reader_id = await profile_id_for(factory, "reader")
        first = await client.get(
            "/api/v1/uptime",
            headers={"X-Watchtower-Profile-Key": token},
        )
        async with factory() as session:
            first_last_used_at = await session.scalar(
                select(ApiKey.last_used_at).where(
                    ApiKey.profile_id == reader_id,
                    ApiKey.credential_kind == "profile_uptime",
                )
            )
        limited = await client.get(
            "/api/v1/uptime",
            headers={"X-Watchtower-Profile-Key": token},
        )
        async with factory() as session:
            final_last_used_at = await session.scalar(
                select(ApiKey.last_used_at).where(
                    ApiKey.profile_id == reader_id,
                    ApiKey.credential_kind == "profile_uptime",
                )
            )

    assert first.status_code == status.HTTP_200_OK
    assert first_last_used_at is not None
    assert limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.json() == {"detail": "Profile uptime rate limit exceeded"}
    assert final_last_used_at == first_last_used_at
