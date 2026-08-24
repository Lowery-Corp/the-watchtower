"""Unit tests for the external authentication service adapter."""

import json
from collections.abc import Callable, Coroutine

import httpx
import pytest

from watchtower.clients.auth_service import (
    AuthServiceClient,
    AuthServiceProtocolError,
    AuthServiceRateLimited,
    AuthServiceUnauthorized,
    AuthServiceUnavailable,
)

Handler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
)


def client_for(handler: Handler) -> tuple[AuthServiceClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(
        base_url="http://auth.test",
        transport=httpx.MockTransport(handler),
    )
    return AuthServiceClient(http_client), http_client


@pytest.mark.asyncio
async def test_login_returns_typed_user_and_secret_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/login"
        assert request.method == "POST"
        assert json.loads(request.read()) == {
            "email": "user@example.com",
            "password": "not-logged",
            "internal": True,
        }
        return httpx.Response(
            200,
            json={
                "id": "dc8805dd-a710-4bf2-8c11-75af04ea52ef",
                "username": "user",
                "is_admin": False,
                "token": "session-secret",
            },
        )

    client, http_client = client_for(handler)
    try:
        session = await client.login(email="user@example.com", password="not-logged")
    finally:
        await http_client.aclose()

    assert str(session.user.id) == "dc8805dd-a710-4bf2-8c11-75af04ea52ef"
    assert session.user.username == "user"
    assert session.user.is_admin is False
    assert session.token.get_secret_value() == "session-secret"
    assert "session-secret" not in repr(session)


@pytest.mark.asyncio
async def test_current_user_maps_unauthorized_without_exposing_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/me"
        assert request.method == "POST"
        assert request.headers["token"] == "invalid-secret"
        assert "Authorization" not in request.headers
        return httpx.Response(401, json={"detail": "Invalid or expired token"})

    client, http_client = client_for(handler)
    try:
        with pytest.raises(AuthServiceUnauthorized) as error:
            await client.get_current_user("invalid-secret")
    finally:
        await http_client.aclose()

    assert "invalid-secret" not in str(error.value)
    assert "invalid-secret" not in repr(error.value)


@pytest.mark.asyncio
async def test_current_user_rejects_malformed_upstream_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "not-a-uuid", "username": "user", "is_admin": False},
        )

    client, http_client = client_for(handler)
    try:
        with pytest.raises(AuthServiceProtocolError):
            await client.get_current_user("session-token")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_current_user_maps_transport_timeout_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("auth unavailable", request=request)

    client, http_client = client_for(handler)
    try:
        with pytest.raises(AuthServiceUnavailable):
            await client.get_current_user("session-token")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_current_user_preserves_safe_retry_after_for_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "17"})

    client, http_client = client_for(handler)
    try:
        with pytest.raises(AuthServiceRateLimited) as error:
            await client.get_current_user("session-token")
    finally:
        await http_client.aclose()

    assert error.value.retry_after == 17
    assert "session-token" not in str(error.value)


@pytest.mark.asyncio
async def test_logout_sends_bearer_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/logout"
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer session-token"
        return httpx.Response(200, json={"ok": True})

    client, http_client = client_for(handler)
    try:
        await client.logout("session-token")
    finally:
        await http_client.aclose()
