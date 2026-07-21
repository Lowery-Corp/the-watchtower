"""Unit tests for bounded, early webhook authentication."""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from starlette.requests import Request
from starlette.types import Message

from watchtower.api.v1.dependencies import webhook_auth
from watchtower.core.config import Settings

Receive = Callable[[], Awaitable[Message]]


def make_request(
    receive: Receive,
    settings: Settings,
    *,
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (name.lower().encode(), value.encode())
        for name, value in (headers or {}).items()
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/webhooks/events",
        "raw_path": b"/api/v1/webhooks/events",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "app": type("App", (), {"state": type("State", (), {"settings": settings})()})(),
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_missing_headers_return_unauthorized_without_consuming_body() -> None:
    calls = 0

    async def receive() -> Message:
        nonlocal calls
        calls += 1
        return {"type": "http.request", "body": b"payload", "more_body": False}

    request = make_request(receive, Settings())

    with pytest.raises(HTTPException) as error:
        await webhook_auth.authenticate_webhook(request)

    assert error.value.status_code == 401
    assert calls == 0


@pytest.mark.asyncio
async def test_stale_headers_are_rejected_before_body_is_consumed() -> None:
    calls = 0

    async def receive() -> Message:
        nonlocal calls
        calls += 1
        return {"type": "http.request", "body": b"payload", "more_body": False}

    settings = Settings(
        webhook_secrets={"scrappy": SecretStr("integration-secret")},
    )
    request = make_request(
        receive,
        settings,
        headers={
            "X-Watchtower-Service": "scrappy",
            "X-Watchtower-Timestamp": "1",
            "X-Watchtower-Signature": "v1=" + ("0" * 64),
        },
    )

    with pytest.raises(HTTPException) as error:
        await webhook_auth.authenticate_webhook(request)

    assert error.value.status_code == 401
    assert calls == 0


@pytest.mark.asyncio
async def test_oversized_single_chunk_is_rejected_before_buffer_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def receive() -> Message:
        return {"type": "http.request", "body": b"x" * 4096, "more_body": False}

    class GuardedBuffer:
        def __len__(self) -> int:
            return 0

        def extend(self, chunk: bytes) -> None:
            del chunk
            raise AssertionError("oversized chunk must not be copied")

    monkeypatch.setattr(webhook_auth, "bytearray", GuardedBuffer, raising=False)
    request = make_request(receive, Settings(max_webhook_body_bytes=1024))

    with pytest.raises(HTTPException) as error:
        await webhook_auth.read_limited_body(request, 1024)

    assert error.value.status_code == 413
