"""Bounded per-process webhook rate limiting."""

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class _Window:
    started_at: float
    requests: int


class FixedWindowRateLimiter:
    """Enforce a fixed request budget per authenticated source and process."""

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock
        self._windows: dict[str, _Window] = {}
        self._lock = asyncio.Lock()

    async def consume(self, key: str) -> int | None:
        """Consume one request or return a positive Retry-After value."""

        async with self._lock:
            now = self._clock()
            window = self._windows.get(key)
            if window is None or now - window.started_at >= self._window_seconds:
                self._windows[key] = _Window(started_at=now, requests=1)
                return None
            if window.requests >= self._max_requests:
                remaining = self._window_seconds - (now - window.started_at)
                return max(1, math.ceil(remaining))
            window.requests += 1
            return None
