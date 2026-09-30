"""Answer cache: an in-process LRU with TTL, or Redis when running more than one replica.

Exact-match on the normalized question. A semantic cache (matching paraphrases)
is on the roadmap; see docs/decisions/0003-exact-match-answer-cache.md.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Protocol


def cache_key(question: str, model: str, corpus_version: str) -> str:
    normalized = " ".join(question.lower().split()).rstrip("?.! ")
    raw = f"{corpus_version}|{model}|{normalized}"
    return "rag:answer:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


class AnswerCache(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any]) -> None: ...


class NullCache:
    def get(self, key: str) -> dict[str, Any] | None:
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        return None


class InMemoryCache:
    def __init__(
        self,
        ttl_seconds: int = 3600,
        max_entries: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def set(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._entries[key] = (self._clock() + self.ttl_seconds, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)


class RedisCache:
    def __init__(self, client: Any, ttl_seconds: int = 3600) -> None:
        self._client = client
        self.ttl_seconds = ttl_seconds

    @classmethod
    def from_url(cls, url: str, ttl_seconds: int = 3600) -> RedisCache:
        import redis  # optional dependency: pip install ".[redis]"

        return cls(redis.Redis.from_url(url), ttl_seconds)

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(key)
        return json.loads(raw) if raw else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._client.setex(key, self.ttl_seconds, json.dumps(value))
