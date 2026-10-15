"""User feedback on answers: the input to the production -> evaluation loop.

Every answer the API serves gets an `answer_id` and a short-lived record of what was asked
and answered. A thumbs up or down refers to that id, so the stored feedback carries the
full context (question, answer, sources) needed to turn a complaint into an eval case,
without trusting the client to send it back.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from rag_service.schemas import QueryResponse


def answer_record(
    response: QueryResponse, question: str, request_id: str, cache_namespace: str
) -> dict[str, Any]:
    """What gets remembered about a served answer, in case someone rates it."""
    return {
        "answer_id": response.answer_id,
        "request_id": request_id,
        "question": question,
        "answer": response.answer,
        "abstained": response.abstained,
        "cached": response.cached,
        "model": response.usage.model,
        "cache_namespace": cache_namespace,
        "retrieved_docs": [chunk.doc_id for chunk in response.retrieved],
        "cited": [
            {"doc_id": c.doc_id, "section": c.section, "quote": c.quote} for c in response.citations
        ],
    }


class FeedbackStore(Protocol):
    def remember(self, record: dict[str, Any]) -> None: ...

    def lookup(self, answer_id: str) -> dict[str, Any] | None: ...

    def add(self, entry: dict[str, Any]) -> None: ...

    def entries(self) -> list[dict[str, Any]]: ...


class LocalFeedbackStore:
    """Single-node store: recent answers in memory, feedback appended to a JSONL file.

    Answers are only kept long enough to be rated (bounded and expiring), while feedback is
    durable. Each feedback line is self-contained, so the file is the export.
    """

    def __init__(
        self,
        path: Path,
        answer_ttl_seconds: int = 7 * 24 * 3600,
        max_answers: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = path
        self.answer_ttl_seconds = answer_ttl_seconds
        self.max_answers = max_answers
        self._clock = clock
        self._answers: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def remember(self, record: dict[str, Any]) -> None:
        with self._lock:
            expires_at = self._clock() + self.answer_ttl_seconds
            self._answers[record["answer_id"]] = (expires_at, record)
            while len(self._answers) > self.max_answers:
                self._answers.popitem(last=False)

    def lookup(self, answer_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._answers.get(answer_id)
            if entry is None:
                return None
            expires_at, record = entry
            if self._clock() >= expires_at:
                del self._answers[answer_id]
                return None
            return record

    def add(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        return read_jsonl(self.path)


class RedisFeedbackStore:
    """Shared across replicas: answers as expiring keys, feedback as an append-only list."""

    ANSWER_PREFIX = "rag:served:"  # distinct from the answer cache's "rag:answer:"
    FEEDBACK_KEY = "rag:feedback"

    def __init__(self, client: Any, answer_ttl_seconds: int = 7 * 24 * 3600) -> None:
        self._client = client
        self.answer_ttl_seconds = answer_ttl_seconds

    @classmethod
    def from_url(cls, url: str, answer_ttl_seconds: int = 7 * 24 * 3600) -> RedisFeedbackStore:
        import redis  # optional dependency: pip install ".[redis]"

        return cls(redis.Redis.from_url(url), answer_ttl_seconds)

    def remember(self, record: dict[str, Any]) -> None:
        key = self.ANSWER_PREFIX + record["answer_id"]
        self._client.setex(key, self.answer_ttl_seconds, json.dumps(record))

    def lookup(self, answer_id: str) -> dict[str, Any] | None:
        raw = self._client.get(self.ANSWER_PREFIX + answer_id)
        return json.loads(raw) if raw else None

    def add(self, entry: dict[str, Any]) -> None:
        self._client.rpush(self.FEEDBACK_KEY, json.dumps(entry))

    def entries(self) -> list[dict[str, Any]]:
        return [json.loads(raw) for raw in self._client.lrange(self.FEEDBACK_KEY, 0, -1)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def latest_per_answer(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One vote per answer: a user who changes their mind, or adds a comment, overrides."""
    latest: dict[str, dict[str, Any]] = {}
    for entry in entries:
        latest.pop(entry["answer_id"], None)  # keep file order of the latest vote
        latest[entry["answer_id"]] = entry
    return list(latest.values())
