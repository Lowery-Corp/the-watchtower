"""SSRF-safe website probe tests."""

import asyncio
import socket
from collections.abc import Callable
from typing import Any

import pytest
from aiohttp import TCPConnector

from watchtower.uptime.probe import (
    ProbeResult,
    SafeResolver,
    UnsafeTargetError,
    is_public_address,
    probe_url,
)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "192.0.2.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
    ],
)
def test_non_global_addresses_are_blocked(address: str) -> None:
    assert is_public_address(address) is False


def test_global_addresses_are_allowed() -> None:
    assert is_public_address("8.8.8.8") is True
    assert is_public_address("2606:4700:4700::1111") is True


async def test_resolver_rejects_entire_answer_set_when_any_address_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeTargetError):
        await SafeResolver().resolve("example.com", 443)


async def test_resolver_returns_only_connector_consumable_public_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    answers = await SafeResolver().resolve("example.com", 443)

    assert len(answers) == 1
    assert answers[0]["hostname"] == "example.com"
    assert answers[0]["host"] == "8.8.8.8"
    assert answers[0]["port"] == 443


class FakeResponse:
    def __init__(self, status: int = 204, error: BaseException | None = None) -> None:
        self.status = status
        self.error = error
        self.read_called = False

    async def __aenter__(self) -> "FakeResponse":
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def read(self) -> bytes:
        self.read_called = True
        raise AssertionError("probe must not read response bodies")


class FakeSession:
    def __init__(self, response: FakeResponse, captured: dict[str, Any], **kwargs: object) -> None:
        self.response = response
        self.captured = captured
        captured["session"] = kwargs

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        connector = self.captured["session"]["connector"]
        await connector.close()

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.captured["request"] = {"url": url, **kwargs}
        return self.response


def session_factory(
    response: FakeResponse, captured: dict[str, Any]
) -> Callable[..., FakeSession]:
    return lambda **kwargs: FakeSession(response, captured, **kwargs)


async def test_probe_does_not_follow_redirects_or_read_bodies() -> None:
    captured: dict[str, Any] = {}
    response = FakeResponse(status=302)

    result = await probe_url(
        "https://example.com/redirect",
        timeout_seconds=3,
        session_factory=session_factory(response, captured),
    )

    assert result.is_up is True
    assert result.status_code == 302
    assert result.failure_kind is None
    assert result.response_time_ms >= 0
    assert response.read_called is False
    assert captured["request"] == {
        "url": "https://example.com/redirect",
        "allow_redirects": False,
    }
    connector = captured["session"]["connector"]
    assert isinstance(connector, TCPConnector)
    assert connector.use_dns_cache is False


async def test_probe_reports_http_and_blocked_target_failures_without_details() -> None:
    http_result = await probe_url(
        "https://example.com/failure",
        session_factory=session_factory(FakeResponse(status=503), {}),
    )
    blocked_result = await probe_url(
        "https://example.com/rebound",
        session_factory=session_factory(
            FakeResponse(error=UnsafeTargetError("private address detail")), {}
        ),
    )

    assert http_result == ProbeResult(
        is_up=False,
        status_code=503,
        response_time_ms=http_result.response_time_ms,
        failure_kind="http",
    )
    assert blocked_result == ProbeResult(
        is_up=False,
        status_code=None,
        response_time_ms=blocked_result.response_time_ms,
        failure_kind="blocked_target",
    )


async def test_probe_blocks_unsafe_literal_before_opening_a_session() -> None:
    session_opened = False
    captured: dict[str, Any] = {}

    def forbidden_factory(**kwargs: object) -> FakeSession:
        nonlocal session_opened
        session_opened = True
        captured["session"] = kwargs
        return FakeSession(FakeResponse(), captured, **kwargs)

    result = await probe_url(
        "http://169.254.169.254/latest/meta-data/",
        session_factory=forbidden_factory,
    )

    assert result == ProbeResult(
        is_up=False,
        status_code=None,
        response_time_ms=0,
        failure_kind="blocked_target",
    )
    assert session_opened is False
