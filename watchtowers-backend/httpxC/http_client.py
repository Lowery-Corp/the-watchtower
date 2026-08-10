from typing import Any

from httpx import AsyncClient, Limits, Timeout

http_client = AsyncClient(
    timeout=Timeout(
        connect=5.0,
        read=30.0,
        write=10.0,
        pool=5.0,
    ),
    limits=Limits(
        max_connections=100,
        max_keepalive_connections=20,
    ),
)


async def make_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
):
    response = await http_client.request(
        method=method,
        url=url,
        headers=headers,
        json=body,
    )

    return response