"""SSRF-safe website probes."""

import asyncio
import socket
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit

from aiohttp import (
    ClientConnectorCertificateError,
    ClientConnectorError,
    ClientError,
    ClientSession,
    ClientSSLError,
    ClientTimeout,
    TCPConnector,
)
from aiohttp.abc import AbstractResolver, ResolveResult

FailureKind = Literal[
    "dns", "blocked_target", "timeout", "tls", "connect", "http", "internal_error"
]


class UnsafeTargetError(ValueError):
    """DNS resolution produced an address outside the public internet."""


@dataclass(frozen=True)
class ProbeResult:
    """Bounded, non-sensitive result persisted by the worker."""

    is_up: bool
    status_code: int | None
    response_time_ms: int
    failure_kind: FailureKind | None


def is_public_address(value: str) -> bool:
    """Return whether an IP (including mapped IPv6) is globally routable."""

    address = ip_address(value)
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def validate_probe_target(url: str) -> None:
    """Reject unsafe URL forms before constructing any network client."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeTargetError("invalid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeTargetError("unsupported URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise UnsafeTargetError("unsafe URL components")
    if port is not None and port != (80 if parsed.scheme == "http" else 443):
        raise UnsafeTargetError("non-standard port")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeTargetError("local hostname")
    try:
        address = ip_address(hostname)
    except ValueError:
        return
    if not is_public_address(str(address)):
        raise UnsafeTargetError("non-public address")


class SafeResolver(AbstractResolver):
    """Resolve hosts once and reject an answer set containing any unsafe IP."""

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_UNSPEC,
    ) -> list[ResolveResult]:
        """Return connector answers only after validating the complete set."""

        infos = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            family=family,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        if not infos:
            raise OSError("DNS returned no addresses")
        addresses = [str(sockaddr[0]) for _, _, _, _, sockaddr in infos]
        if any(not is_public_address(address) for address in addresses):
            raise UnsafeTargetError("DNS target is not globally routable")
        answers: list[ResolveResult] = []
        seen: set[tuple[str, int]] = set()
        for resolved_family, _, proto, _, sockaddr in infos:
            address = str(sockaddr[0])
            resolved_port = int(sockaddr[1])
            key = (address, resolved_port)
            if key in seen:
                continue
            seen.add(key)
            answers.append(
                ResolveResult(
                    hostname=host,
                    host=address,
                    port=resolved_port,
                    family=resolved_family,
                    proto=proto,
                    flags=socket.AI_NUMERICHOST,
                )
            )
        return answers

    async def close(self) -> None:
        """Release resolver resources (none are retained)."""


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((monotonic() - started_at) * 1000))


async def probe_url(
    url: str,
    *,
    timeout_seconds: float = 10.0,
    session_factory: Callable[..., Any] | None = None,
) -> ProbeResult:
    """Probe one URL without redirects or response-body consumption."""

    started_at = monotonic()
    try:
        validate_probe_target(url)
    except UnsafeTargetError:
        return ProbeResult(
            is_up=False,
            status_code=None,
            response_time_ms=0,
            failure_kind="blocked_target",
        )

    factory = session_factory or ClientSession
    connector = TCPConnector(resolver=SafeResolver(), use_dns_cache=False)
    try:
        async with factory(
            connector=connector,
            timeout=ClientTimeout(total=timeout_seconds),
            headers={"User-Agent": "Watchtower-Uptime/1.0"},
        ) as session:
            async with session.get(url, allow_redirects=False) as response:
                status_code = int(response.status)
                is_up = 200 <= status_code <= 399
                return ProbeResult(
                    is_up=is_up,
                    status_code=status_code,
                    response_time_ms=_elapsed_ms(started_at),
                    failure_kind=None if is_up else "http",
                )
    except UnsafeTargetError:
        failure_kind: FailureKind = "blocked_target"
    except TimeoutError:
        failure_kind = "timeout"
    except (ClientConnectorCertificateError, ClientSSLError):
        failure_kind = "tls"
    except ClientConnectorError as exc:
        failure_kind = "dns" if isinstance(exc.os_error, socket.gaierror) else "connect"
    except ClientError:
        failure_kind = "connect"
    finally:
        if not connector.closed:
            await connector.close()
    return ProbeResult(
        is_up=False,
        status_code=None,
        response_time_ms=_elapsed_ms(started_at),
        failure_kind=failure_kind,
    )
