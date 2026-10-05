import datetime as dt
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from rag_service.api import build_budget, build_pipeline, create_app
from rag_service.budget import BudgetExceeded, DailyBudget, InMemorySpendStore, RedisSpendStore
from rag_service.llm import AnthropicProvider, Generation


def utc(*args) -> float:
    return dt.datetime(*args, tzinfo=dt.UTC).timestamp()


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_budget_blocks_at_the_limit_and_resets_at_utc_midnight():
    clock = Clock(utc(2026, 10, 5, 23, 0))
    budget = DailyBudget(1.0, clock=clock)
    budget.check()
    budget.record(0.6)
    budget.check()
    budget.record(0.6)  # the request that crosses the limit is allowed to finish
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.check()
    assert excinfo.value.retry_after_seconds == 3600
    clock.now = utc(2026, 10, 6, 0, 0, 1)
    budget.check()
    assert budget.spent_today() == 0.0


def test_warning_fires_once_when_crossing_the_threshold():
    warnings = []
    budget = DailyBudget(10.0, on_warning=lambda spent, limit: warnings.append(spent))
    for _ in range(5):
        budget.record(2.0)  # 2, 4, 6, 8 (crosses 80%), 10
    assert warnings == [8.0]


def test_zero_disables_the_cap():
    budget = DailyBudget(0)
    budget.record(1_000.0)
    budget.check()
    assert budget.snapshot()["daily_budget_usd"] is None


def test_in_memory_store_keeps_only_the_current_day():
    store = InMemorySpendStore()
    store.add("2026-10-05", 1.0)
    store.add("2026-10-06", 2.0)
    assert store.get("2026-10-05") == 0.0
    assert store.get("2026-10-06") == 2.0


def test_redis_store_is_shared_and_expires():
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, float] = {}
            self.ttl: dict[str, int] = {}

        def incrbyfloat(self, key, amount):
            self.values[key] = self.values.get(key, 0.0) + amount
            return self.values[key]

        def expire(self, key, seconds):
            self.ttl[key] = seconds

        def get(self, key):
            value = self.values.get(key)
            return None if value is None else str(value).encode()

    client = FakeRedis()
    replica_a, replica_b = RedisSpendStore(client), RedisSpendStore(client)
    replica_a.add("2026-10-05", 0.25)
    assert replica_b.add("2026-10-05", 0.5) == 0.75
    assert replica_a.get("2026-10-05") == 0.75
    assert client.ttl["rag:spend:2026-10-05"] == 2 * 24 * 3600


class PricedProvider:
    """Costs $0.40 per answer at Opus prices (100k input tokens)."""

    name = "anthropic"
    fingerprint = "priced"

    def __init__(self, model: str = "claude-opus-5-5") -> None:
        self.model = model
        self.calls = 0

    def generate(self, question, sources):
        self.calls += 1
        return Generation(
            text=f"{sources[0].text[:40]} [1]",
            citations=[(0, sources[0].text[:40])],
            model=self.model,
            input_tokens=100_000,
            output_tokens=0,
        )


def test_api_refuses_new_answers_but_keeps_free_ones_after_the_cap(settings):
    capped = replace(settings, daily_budget_usd=1.0)
    provider = PricedProvider()
    client = TestClient(create_app(capped, build_pipeline(capped, provider)))
    questions = [
        "When is the holiday change freeze?",
        "How many PTO days do I get?",
        "What is the daily meal allowance?",
    ]
    for question in questions:  # $0.40 each; the third pushes spend to $1.20
        assert client.post("/v1/query", json={"question": question}).status_code == 200

    refused = client.post("/v1/query", json={"question": "How do I get production access?"})
    assert refused.status_code == 503
    assert int(refused.headers["retry-after"]) > 0
    assert "budget" in refused.json()["detail"]
    assert provider.calls == 3, "no model call after the cap"

    cached = client.post("/v1/query", json={"question": questions[0]})
    assert cached.status_code == 200 and cached.json()["cached"] is True
    no_match = client.post("/v1/query", json={"question": "zebra xylophone quartz"})
    assert no_match.status_code == 200 and no_match.json()["abstained"] is True

    metrics = client.get("/v1/metrics").json()
    assert metrics["budget_rejections"] == 1
    assert metrics["spent_today_usd"] == pytest.approx(1.2)
    assert metrics["budget_remaining_usd"] == 0.0


def test_unpriced_fallback_model_still_counts(settings):
    class FallbackProvider(PricedProvider):
        """Configured as Opus, but the answer comes back from a model with no known price."""

        def generate(self, question, sources):
            generation = super().generate(question, sources)
            generation.model = "some-fallback-model"
            return generation

    pipeline = build_pipeline(replace(settings, daily_budget_usd=5.0), FallbackProvider())
    pipeline.answer("When is the holiday change freeze?")
    assert pipeline.budget.spent_today() == pytest.approx(0.4)  # counted at Opus prices


def test_startup_fails_closed_for_unpriced_models(settings):
    unpriced = AnthropicProvider(model="claude-unknown-model", client=object())
    with pytest.raises(ValueError, match="no price"):
        build_budget(replace(settings, daily_budget_usd=10.0), unpriced)
    assert build_budget(replace(settings, daily_budget_usd=0), unpriced) is None


def test_offline_provider_never_spends(settings):
    pipeline = build_pipeline(replace(settings, daily_budget_usd=0.01, cache_backend="none"))
    for _ in range(3):
        pipeline.answer("When is the holiday change freeze?")
    assert pipeline.budget.spent_today() == 0.0
