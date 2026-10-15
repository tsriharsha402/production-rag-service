import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest, multiprocess
from prometheus_client.parser import text_string_to_metric_families

from rag_service.api import build_budget, create_app
from rag_service.budget import DailyBudget
from rag_service.llm import LLMError

ROOT = Path(__file__).resolve().parent.parent


def scrape(client) -> dict[tuple[str, frozenset], float]:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    return parse(response.text)


def parse(text: str) -> dict[tuple[str, frozenset], float]:
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


def value(samples, name, **labels) -> float:
    return samples[(name, frozenset(labels.items()))]


def test_series_exist_at_zero_before_any_traffic(app):
    samples = scrape(TestClient(app))
    assert value(samples, "rag_answers_total", cached="false", abstained="false") == 0
    assert value(samples, "rag_feedback_votes_total", rating="down") == 0
    assert value(samples, "rag_rate_limited_total", endpoint="feedback") == 0
    assert value(samples, "rag_llm_errors_total", retryable="true") == 0


def test_configured_model_series_start_at_zero(app):
    samples = scrape(TestClient(app))
    assert value(samples, "rag_llm_cost_usd_total", model="offline-extractive") == 0
    assert (
        value(samples, "rag_llm_tokens_total", model="offline-extractive", direction="input") == 0
    )


def test_answers_latency_and_cache_hits_are_counted(app):
    client = TestClient(app)
    client.post("/v1/query", json={"question": "When is the holiday change freeze?"})
    client.post("/v1/query", json={"question": "When is the holiday change freeze?"})
    client.post("/v1/query", json={"question": "zebra xylophone quartz"})
    samples = scrape(client)
    assert value(samples, "rag_answers_total", cached="false", abstained="false") == 1
    assert value(samples, "rag_answers_total", cached="true", abstained="false") == 1
    assert value(samples, "rag_answers_total", cached="false", abstained="true") == 1
    assert value(samples, "rag_answer_latency_seconds_count", cached="false") == 2
    assert value(samples, "rag_answer_latency_seconds_count", cached="true") == 1
    tokens = value(samples, "rag_llm_tokens_total", model="offline-extractive", direction="input")
    assert tokens > 0


def test_changed_vote_is_a_retraction_plus_a_new_vote(app):
    client = TestClient(app)
    answer_id = client.post("/v1/query", json={"question": "How many PTO days?"}).json()[
        "answer_id"
    ]
    for rating in ("up", "down", "down"):  # the repeat is a comment, not a new vote
        client.post("/v1/feedback", json={"answer_id": answer_id, "rating": rating})
    samples = scrape(client)
    votes = {r: value(samples, "rag_feedback_votes_total", rating=r) for r in ("up", "down")}
    retracted = {
        r: value(samples, "rag_feedback_retracted_total", rating=r) for r in ("up", "down")
    }
    assert votes == {"up": 1, "down": 1}
    assert retracted == {"up": 1, "down": 0}
    # The current tally, as dashboards compute it: votes - retracted.
    assert votes["down"] - retracted["down"] == 1
    assert votes["up"] - retracted["up"] == 0


def test_errors_and_rate_limits_are_labelled(settings, pipeline):
    from dataclasses import replace

    class DownProvider:
        name, model, fingerprint = "down", "down", "down"

        def generate(self, question, sources):
            raise LLMError("bad request", retryable=False)

    pipeline.provider = DownProvider()
    client = TestClient(create_app(replace(settings, rate_limit_per_minute=1), pipeline))
    assert (
        client.post("/v1/query", json={"question": "When is the change freeze?"}).status_code == 502
    )
    client.post("/v1/query", json={"question": "When is the change freeze?"})
    client.post("/v1/feedback", json={"answer_id": "x", "rating": "up"})
    client.post("/v1/feedback", json={"answer_id": "x", "rating": "up"})
    samples = scrape(client)
    assert value(samples, "rag_llm_errors_total", retryable="false") == 1
    assert value(samples, "rag_rate_limited_total", endpoint="query") == 1
    assert value(samples, "rag_rate_limited_total", endpoint="feedback") == 1


def test_service_info_identifies_the_deployment(app, pipeline):
    samples = scrape(TestClient(app))
    [labels] = [dict(labels) for name, labels in samples if name == "rag_service_info"]
    assert labels["model"] == "offline-extractive"
    assert labels["cache_namespace"] == pipeline.cache_namespace
    assert labels["corpus_version"] == pipeline.corpus_version


def test_budget_gauges_read_the_shared_store(settings, pipeline):
    from dataclasses import replace

    pipeline.budget = build_budget(replace(settings, daily_budget_usd=5.0), pipeline.provider)
    pipeline.budget.record(1.25)
    samples = scrape(TestClient(create_app(settings, pipeline)))
    assert value(samples, "rag_budget_limit_usd") == 5.0
    assert value(samples, "rag_budget_spent_today_usd") == 1.25
    assert value(samples, "rag_budget_store_up") == 1


def test_unreadable_budget_store_is_reported_not_fatal(settings, pipeline):
    class BrokenStore:
        def add(self, day, amount):
            raise ConnectionError("redis down")

        def get(self, day):
            raise ConnectionError("redis down")

    pipeline.budget = DailyBudget(5.0, BrokenStore())
    samples = scrape(TestClient(create_app(settings, pipeline)))
    assert value(samples, "rag_budget_store_up") == 0
    assert ("rag_budget_spent_today_usd", frozenset()) not in samples


WORKER = """
from rag_service.metrics import Metrics
metrics = Metrics()
for _ in range({n}):
    metrics.record_answer(12.0, cached=False, abstained=False, input_tokens=100,
                          output_tokens=20, cost_usd=0.01, model="m")
metrics.record_feedback("down")
"""


def test_counts_from_separate_worker_processes_add_up(tmp_path):
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}
    for n in (2, 3):  # two "uvicorn workers", each with its own memory
        subprocess.run([sys.executable, "-c", WORKER.format(n=n)], env=env, check=True)

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=str(tmp_path))
    samples = parse(generate_latest(registry).decode())
    assert value(samples, "rag_answers_total", cached="false", abstained="false") == 5
    assert value(samples, "rag_feedback_votes_total", rating="down") == 2
    assert value(samples, "rag_llm_cost_usd_total", model="m") == 0.05
    assert value(samples, "rag_answer_latency_seconds_count", cached="false") == 5


def exported_metric_names(app, settings, pipeline) -> set[str]:
    from dataclasses import replace

    pipeline.budget = build_budget(replace(settings, daily_budget_usd=5.0), pipeline.provider)
    client = TestClient(create_app(settings, pipeline))
    answer = client.post("/v1/query", json={"question": "How many PTO days?"}).json()
    client.post("/v1/feedback", json={"answer_id": answer["answer_id"], "rating": "up"})
    return {name for name, _ in scrape(client)}


def referenced_metric_names(text: str) -> set[str]:
    return set(re.findall(r"\brag_[a-z_]+\b", text))


def test_dashboard_only_uses_metrics_the_service_exports(app, settings, pipeline):
    exported = exported_metric_names(app, settings, pipeline)
    dashboard = (ROOT / "deploy/grafana/dashboards/rag-service.json").read_text()
    missing = referenced_metric_names(dashboard) - exported
    assert not missing, f"dashboard queries metrics the service doesn't export: {missing}"


def test_alert_rules_only_use_metrics_the_service_exports(app, settings, pipeline):
    exported = exported_metric_names(app, settings, pipeline)
    rules = yaml.safe_load((ROOT / "deploy/prometheus/alerts.yml").read_text())
    exprs = " ".join(rule["expr"] for group in rules["groups"] for rule in group["rules"])
    missing = referenced_metric_names(exprs) - exported
    assert not missing, f"alert rules query metrics the service doesn't export: {missing}"
