"""In-process service metrics: volume, cache efficiency, latency and spend."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


class Metrics:
    def __init__(self, window: int = 1000) -> None:
        self._lock = threading.Lock()
        self._latencies: deque[float] = deque(maxlen=window)
        self.requests = 0
        self.cache_hits = 0
        self.abstentions = 0
        self.errors = 0
        self.rate_limited = 0
        self.budget_rejections = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def record_answer(
        self,
        latency_ms: float,
        cached: bool,
        abstained: bool,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None,
    ) -> None:
        with self._lock:
            self.requests += 1
            self._latencies.append(latency_ms)
            if cached:
                self.cache_hits += 1
            else:
                self.input_tokens += input_tokens
                self.output_tokens += output_tokens
                self.cost_usd += cost_usd or 0.0
            if abstained:
                self.abstentions += 1

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    def record_rate_limited(self) -> None:
        with self._lock:
            self.rate_limited += 1

    def record_budget_rejection(self) -> None:
        with self._lock:
            self.budget_rejections += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latencies = list(self._latencies)
            answered = max(self.requests, 1)
            return {
                "requests": self.requests,
                "cache_hits": self.cache_hits,
                "cache_hit_rate": round(self.cache_hits / answered, 4),
                "abstentions": self.abstentions,
                "errors": self.errors,
                "rate_limited": self.rate_limited,
                "budget_rejections": self.budget_rejections,
                "latency_ms_p50": round(percentile(latencies, 50), 1),
                "latency_ms_p95": round(percentile(latencies, 95), 1),
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_cost_usd": round(self.cost_usd, 6),
                "avg_cost_per_request_usd": round(self.cost_usd / answered, 6),
            }
