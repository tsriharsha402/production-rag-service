from fastapi.testclient import TestClient

from rag_service.api import create_app
from rag_service.llm import LLMError


def test_healthz(app):
    body = TestClient(app).get("/healthz").json()
    assert body["status"] == "ok"
    assert body["provider"] == "offline"
    assert body["chunks_indexed"] > 0
    assert len(body["cache_namespace"]) == 16


def test_query_returns_grounded_answer_with_citations(app):
    response = TestClient(app).post(
        "/v1/query", json={"question": "When is the holiday change freeze?"}
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    body = response.json()
    assert "December 15" in body["answer"]
    assert body["citations"][0]["doc_id"] == "deployment-process"
    assert body["citations"][0]["quote"] in body["answer"]
    assert body["retrieved"][0]["ref"] == 1
    assert body["cached"] is False
    assert body["usage"]["cost_usd"] == 0.0


def test_repeated_question_is_served_from_cache(app):
    client = TestClient(app)
    client.post("/v1/query", json={"question": "What is the daily meal allowance?"})
    second = client.post("/v1/query", json={"question": "what is the daily meal allowance"}).json()
    assert second["cached"] is True
    metrics = client.get("/v1/metrics").json()
    assert metrics["requests"] == 2
    assert metrics["cache_hits"] == 1
    assert metrics["cache_hit_rate"] == 0.5


def test_irrelevant_question_abstains_without_calling_the_llm(settings, pipeline):
    class ExplodingProvider:
        name, model, fingerprint = "exploding", "none", "exploding"

        def generate(self, question, sources):
            raise AssertionError("LLM should not be called when nothing is retrieved")

    pipeline.provider = ExplodingProvider()
    body = (
        TestClient(create_app(settings, pipeline))
        .post("/v1/query", json={"question": "zebra xylophone quartz"})
        .json()
    )
    assert body["abstained"] is True
    assert body["usage"]["cost_usd"] == 0.0


def test_rate_limit_returns_429_with_retry_after(settings, pipeline):
    from dataclasses import replace

    client = TestClient(create_app(replace(settings, rate_limit_per_minute=1), pipeline))
    assert client.post("/v1/query", json={"question": "How many PTO days?"}).status_code == 200
    limited = client.post("/v1/query", json={"question": "How many PTO days?"})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert client.get("/v1/metrics").json()["rate_limited"] == 1


def test_llm_outage_returns_503(settings, pipeline):
    class DownProvider:
        name, model, fingerprint = "down", "down", "down"

        def generate(self, question, sources):
            raise LLMError("overloaded", retryable=True)

    pipeline.provider = DownProvider()
    client = TestClient(create_app(settings, pipeline))
    response = client.post("/v1/query", json={"question": "When is the change freeze?"})
    assert response.status_code == 503
    assert client.get("/v1/metrics").json()["errors"] == 1


def test_input_validation(app):
    client = TestClient(app)
    assert client.post("/v1/query", json={"question": ""}).status_code == 422
    assert client.post("/v1/query", json={"question": "x" * 1001}).status_code == 422


def test_changing_answer_settings_never_serves_stale_cached_answers(settings, pipeline):
    from rag_service import llm
    from rag_service.llm import AnthropicProvider

    question = {"question": "When is the holiday change freeze?"}
    client = TestClient(create_app(settings, pipeline))
    assert client.post("/v1/query", json=question).json()["cached"] is False
    assert client.post("/v1/query", json=question).json()["cached"] is True

    # Retrieval settings are part of the key.
    pipeline.top_k = 6
    assert client.post("/v1/query", json=question).json()["cached"] is False

    # So are the model's settings and the prompt (checked without calling the API).
    provider = AnthropicProvider(client=object())
    pipeline.provider = provider
    namespaces = {pipeline.cache_namespace}
    provider.effort = "low"
    namespaces.add(pipeline.cache_namespace)
    provider.model = "claude-sonnet-5-5"
    namespaces.add(pipeline.cache_namespace)
    original = llm.PROMPT_VERSION
    try:
        llm.PROMPT_VERSION = "edited"
        namespaces.add(pipeline.cache_namespace)
    finally:
        llm.PROMPT_VERSION = original
    assert len(namespaces) == 4
