from __future__ import annotations

import time


class RateLimiter:
    """Token-bucket style rate limiter: ensures at least 1/max_per_second seconds between calls."""

    def __init__(self, max_per_second: float = 5.0) -> None:
        self._min_interval = 1.0 / max_per_second
        self._last_call: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()
