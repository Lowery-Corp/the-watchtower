"""Shared webhook rate-limit use case."""

from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.repositories.webhook_rate_limits import (
    consume_webhook_rate_limit as consume_webhook_rate_limit_row,
)


async def consume_webhook_rate_limit(
    session: AsyncSession,
    *,
    identity: str,
    max_requests: int,
    window_seconds: int,
) -> int | None:
    """Consume one slot and commit that decision before request processing continues."""

    async with session.begin():
        return await consume_webhook_rate_limit_row(
            session,
            identity=identity,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
