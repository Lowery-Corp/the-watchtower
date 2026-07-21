"""Unit tests for authenticated-source request budgets."""

import pytest

from watchtower.core.rate_limit import FixedWindowRateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_enforces_budget_and_resets_after_window() -> None:
    now = 100.0

    def clock() -> float:
        return now

    limiter = FixedWindowRateLimiter(
        max_requests=2,
        window_seconds=10,
        clock=clock,
    )

    assert await limiter.consume("scrappy") is None
    assert await limiter.consume("scrappy") is None
    assert await limiter.consume("scrappy") == 10
    assert await limiter.consume("offload") is None

    now = 111.0
    assert await limiter.consume("scrappy") is None
