"""Per-client token-bucket rate limiting.

Protects the LLM budget as much as the service: one runaway client should not
be able to spend the month's API budget in an afternoon.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = float(per_minute)
        self.refill_per_second = per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str) -> tuple[bool, float]:
        """Consume one token. Returns ``(allowed, retry_after_seconds)``."""
        if self.capacity <= 0:
            return True, 0.0
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(client_id)
            if bucket is None:
                bucket = self._buckets[client_id] = _Bucket(self.capacity, now)
            bucket.tokens = min(
                self.capacity, bucket.tokens + (now - bucket.updated_at) * self.refill_per_second
            )
            bucket.updated_at = now
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True, 0.0
            return False, (1 - bucket.tokens) / self.refill_per_second
