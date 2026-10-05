"""Daily spend cap for model calls.

Checked right before every paid model call. When the day's budget is used up, new answers
are refused until midnight UTC, while cached answers and abstentions (which cost nothing)
keep working. See docs/decisions/0006-daily-spend-cap.md.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol


class BudgetExceeded(Exception):
    def __init__(self, spent_usd: float, limit_usd: float, retry_after_seconds: int) -> None:
        super().__init__(f"Daily budget of ${limit_usd:.2f} reached (${spent_usd:.4f} spent)")
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd
        self.retry_after_seconds = retry_after_seconds


class SpendStore(Protocol):
    def get(self, day: str) -> float: ...

    def add(self, day: str, amount: float) -> float:
        """Add to the day's total and return the new total."""
        ...


class InMemorySpendStore:
    """Per-process totals. Use RedisSpendStore when running more than one replica."""

    def __init__(self) -> None:
        self._totals: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, day: str) -> float:
        with self._lock:
            return self._totals.get(day, 0.0)

    def add(self, day: str, amount: float) -> float:
        with self._lock:
            # Only today's total matters; drop older days so the dict can't grow forever.
            self._totals = {day: self._totals.get(day, 0.0) + amount}
            return self._totals[day]


class RedisSpendStore:
    """Shared totals across replicas. INCRBYFLOAT is atomic, so concurrent requests on
    different replicas can't lose each other's spend."""

    def __init__(self, client: Any, prefix: str = "rag:spend:") -> None:
        self._client = client
        self._prefix = prefix

    @classmethod
    def from_url(cls, url: str) -> RedisSpendStore:
        import redis  # optional dependency: pip install ".[redis]"

        return cls(redis.Redis.from_url(url))

    def get(self, day: str) -> float:
        raw = self._client.get(self._prefix + day)
        return float(raw) if raw else 0.0

    def add(self, day: str, amount: float) -> float:
        key = self._prefix + day
        total = float(self._client.incrbyfloat(key, amount))
        self._client.expire(key, 2 * 24 * 3600)
        return total


class DailyBudget:
    def __init__(
        self,
        limit_usd: float,
        store: SpendStore | None = None,
        warn_ratio: float = 0.8,
        on_warning: Callable[[float, float], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.limit_usd = limit_usd
        self.warn_ratio = warn_ratio
        self._store = store or InMemorySpendStore()
        self._on_warning = on_warning
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return self.limit_usd > 0

    def _now(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self._clock(), tz=dt.UTC)

    def _today(self) -> str:
        return self._now().date().isoformat()

    def seconds_until_reset(self) -> int:
        now = self._now()
        midnight = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(), dt.UTC)
        return max(1, int((midnight - now).total_seconds()))

    def spent_today(self) -> float:
        return self._store.get(self._today())

    def check(self) -> None:
        """Raise BudgetExceeded if today's budget is used up. Call before a paid model call.

        A request that starts just under the limit can overshoot it by its own cost; with
        many concurrent requests the overshoot is bounded by one request each.
        """
        if not self.enabled:
            return
        spent = self.spent_today()
        if spent >= self.limit_usd:
            raise BudgetExceeded(spent, self.limit_usd, self.seconds_until_reset())

    def record(self, cost_usd: float) -> None:
        if not self.enabled or cost_usd <= 0:
            return
        total = self._store.add(self._today(), cost_usd)
        threshold = self.limit_usd * self.warn_ratio
        # Fires exactly once per day: only for the request whose cost crosses the threshold.
        if self._on_warning and total - cost_usd < threshold <= total:
            self._on_warning(total, self.limit_usd)

    def snapshot(self) -> dict[str, Any]:
        spent = self.spent_today()
        return {
            "daily_budget_usd": self.limit_usd if self.enabled else None,
            "spent_today_usd": round(spent, 6),
            "budget_remaining_usd": round(max(self.limit_usd - spent, 0.0), 6)
            if self.enabled
            else None,
            "budget_resets_in_seconds": self.seconds_until_reset(),
        }
