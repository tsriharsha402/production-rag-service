"""Service metrics: volume, cache efficiency, latency, spend and feedback.

Every event is recorded in two views:

- **Prometheus** (`GET /metrics`): cumulative counters and histograms that Prometheus
  aggregates across worker processes and replicas. The source of truth for dashboards and
  alerts. With several workers per container, set PROMETHEUS_MULTIPROC_DIR (see the README).
- **In-process snapshot** (`GET /v1/metrics`): readable without a Prometheus server, used
  by the UI. It only covers the process that serves the request and resets on restart.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from collections.abc import Iterator
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram, multiprocess
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

logger = logging.getLogger("rag_service")

# From cache hits (~1 ms) to slow model calls with long answers (tens of seconds).
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


class Metrics:
    def __init__(self, window: int = 1000, registry: CollectorRegistry | None = None) -> None:
        self._lock = threading.Lock()
        self._latencies: deque[float] = deque(maxlen=window)
        self.requests = 0
        self.cache_hits = 0
        self.abstentions = 0
        self.errors = 0
        self.rate_limited = 0
        self.budget_rejections = 0
        self.feedback_up = 0
        self.feedback_down = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

        # One registry per app, so tests (and anything else creating several apps in one
        # process) never collide on the global default registry.
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self._answers = Counter(
            "rag_answers_total", "Answers served.", ["cached", "abstained"], registry=r
        )
        self._latency = Histogram(
            "rag_answer_latency_seconds",
            "Time to produce an answer, cache lookups included.",
            ["cached"],
            buckets=LATENCY_BUCKETS,
            registry=r,
        )
        self._tokens = Counter(
            "rag_llm_tokens_total", "Model tokens billed.", ["model", "direction"], registry=r
        )
        self._cost = Counter("rag_llm_cost_usd_total", "Model spend in USD.", ["model"], registry=r)
        self._errors = Counter(
            "rag_llm_errors_total", "Failed model calls.", ["retryable"], registry=r
        )
        self._rate_limited = Counter(
            "rag_rate_limited_total",
            "Requests rejected by rate limiting.",
            ["endpoint"],
            registry=r,
        )
        self._budget_rejections = Counter(
            "rag_budget_rejections_total",
            "Questions refused because the daily budget was used up.",
            registry=r,
        )
        # A vote that is changed counts as a retraction of the old rating plus a vote for the
        # new one, so votes - retracted is the current tally and both stay monotonic counters.
        self._votes = Counter(
            "rag_feedback_votes_total", "Thumbs up/down votes cast.", ["rating"], registry=r
        )
        self._retracted = Counter(
            "rag_feedback_retracted_total",
            "Votes replaced by a different rating on the same answer.",
            ["rating"],
            registry=r,
        )
        # Create every fixed label combination up front, so the series exist (at 0) from the
        # first scrape and rate() and ratios work before the first event of each kind.
        for cached in ("true", "false"):
            self._latency.labels(cached=cached)
            for abstained in ("true", "false"):
                self._answers.labels(cached=cached, abstained=abstained)
        for retryable in ("true", "false"):
            self._errors.labels(retryable=retryable)
        for endpoint in ("query", "feedback"):
            self._rate_limited.labels(endpoint=endpoint)
        for rating in ("up", "down"):
            self._votes.labels(rating=rating)
            self._retracted.labels(rating=rating)

    def init_model(self, model: str) -> None:
        """Start a model's token and cost series at 0. A series born on its first increment
        has no earlier sample to compare against, so rate() misses that first increment."""
        self._tokens.labels(model=model, direction="input")
        self._tokens.labels(model=model, direction="output")
        self._cost.labels(model=model)

    def record_answer(
        self,
        latency_ms: float,
        cached: bool,
        abstained: bool,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None,
        model: str = "unknown",
    ) -> None:
        labels = {"cached": _label(cached)}
        self._answers.labels(**labels, abstained=_label(abstained)).inc()
        self._latency.labels(**labels).observe(latency_ms / 1000)
        if not cached:
            self._tokens.labels(model=model, direction="input").inc(input_tokens)
            self._tokens.labels(model=model, direction="output").inc(output_tokens)
            self._cost.labels(model=model).inc(cost_usd or 0.0)
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

    def record_error(self, retryable: bool = True) -> None:
        self._errors.labels(retryable=_label(retryable)).inc()
        with self._lock:
            self.errors += 1

    def record_rate_limited(self, endpoint: str = "query") -> None:
        self._rate_limited.labels(endpoint=endpoint).inc()
        if endpoint != "query":
            return  # the snapshot's count has always meant questions
        with self._lock:
            self.rate_limited += 1

    def record_budget_rejection(self) -> None:
        self._budget_rejections.inc()
        with self._lock:
            self.budget_rejections += 1

    def record_feedback(self, rating: str, previous: str | None = None) -> None:
        """Count a vote. `previous` is the answer's earlier rating, if it had one: a repeat
        (adding a comment) changes nothing, a change moves the vote."""
        if previous == rating:
            return
        if previous is not None:
            self._retracted.labels(rating=previous).inc()
        self._votes.labels(rating=rating).inc()
        with self._lock:
            if previous == "up":
                self.feedback_up -= 1
            elif previous == "down":
                self.feedback_down -= 1
            if rating == "up":
                self.feedback_up += 1
            else:
                self.feedback_down += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latencies = list(self._latencies)
            answered = max(self.requests, 1)
            rated = self.feedback_up + self.feedback_down
            return {
                "requests": self.requests,
                "cache_hits": self.cache_hits,
                "cache_hit_rate": round(self.cache_hits / answered, 4),
                "abstentions": self.abstentions,
                "errors": self.errors,
                "rate_limited": self.rate_limited,
                "budget_rejections": self.budget_rejections,
                "feedback_up": self.feedback_up,
                "feedback_down": self.feedback_down,
                # Share of rated answers that got a thumbs down; None until anything is rated.
                "thumbs_down_rate": round(self.feedback_down / rated, 4) if rated else None,
                "latency_ms_p50": round(percentile(latencies, 50), 1),
                "latency_ms_p95": round(percentile(latencies, 95), 1),
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_cost_usd": round(self.cost_usd, 6),
                "avg_cost_per_request_usd": round(self.cost_usd / answered, 6),
            }


class ServiceCollector(Collector):
    """State read at scrape time rather than counted: what is deployed, and today's spend.

    Spend lives in the budget store (Redis when replicas share it), so reading it per scrape
    reports the shared total instead of one process's share.
    """

    def __init__(self, pipeline: Any, version: str) -> None:
        self.pipeline = pipeline
        self.version = version

    def collect(self) -> Iterator[Metric]:
        info = GaugeMetricFamily(
            "rag_service_info",
            "Always 1. Labels identify what is deployed, to compare metrics across releases.",
            labels=["version", "provider", "model", "corpus_version", "cache_namespace"],
        )
        p = self.pipeline
        info.add_metric(
            [self.version, p.provider.name, p.provider.model, p.corpus_version, p.cache_namespace],
            1,
        )
        yield info

        budget = p.budget
        if budget is None:
            return
        up = GaugeMetricFamily(
            "rag_budget_store_up", "1 if the spend store could be read on this scrape."
        )
        try:
            snapshot = budget.snapshot()
        except Exception as exc:  # e.g. Redis down: report it instead of failing the scrape
            logger.warning(json.dumps({"event": "budget_store_unreadable", "error": str(exc)}))
            up.add_metric([], 0)
            yield up
            return
        up.add_metric([], 1)
        yield up
        yield GaugeMetricFamily(
            "rag_budget_spent_today_usd",
            "Model spend so far in the current UTC day.",
            value=snapshot["spent_today_usd"],
        )
        if snapshot["daily_budget_usd"] is not None:
            yield GaugeMetricFamily(
                "rag_budget_limit_usd",
                "Daily spend cap in USD.",
                value=snapshot["daily_budget_usd"],
            )


def exposition_registry(metrics: Metrics, pipeline: Any, version: str) -> CollectorRegistry:
    """The registry `/metrics` serves.

    With PROMETHEUS_MULTIPROC_DIR set (several worker processes), counters are written to
    shared files and read back from all workers; otherwise this process's registry is used.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = metrics.registry
    registry.register(ServiceCollector(pipeline, version))
    return registry


def _label(value: bool) -> str:
    return "true" if value else "false"
