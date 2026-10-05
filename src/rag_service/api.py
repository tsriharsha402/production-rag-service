"""HTTP API.

Run locally:  uvicorn rag_service.api:create_app --factory --reload
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from rag_service import __version__
from rag_service.cache import AnswerCache, InMemoryCache, NullCache, RedisCache
from rag_service.config import Settings
from rag_service.documents import chunk_document, corpus_version, load_documents
from rag_service.llm import AnthropicProvider, LLMError, LLMProvider, OfflineProvider
from rag_service.metrics import Metrics
from rag_service.pipeline import RAGPipeline
from rag_service.rate_limit import RateLimiter
from rag_service.retrieval import BM25Index
from rag_service.schemas import QueryRequest, QueryResponse

logger = logging.getLogger("rag_service")


def client_ip(request: Request, trusted_proxy_hops: int = 0) -> str:
    """The address to rate-limit on.

    Never trusts identity headers the client controls: a client could send a new value with
    every request and never be limited. With no trusted proxies this is the TCP peer address.
    Behind N trusted proxies, each proxy appends the address it received the request from to
    X-Forwarded-For, so the real client is the Nth entry from the right; anything further left
    may be forged.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if len(hops) >= trusted_proxy_hops:
        return hops[-trusted_proxy_hops]
    return peer


def build_provider(settings: Settings) -> LLMProvider:
    provider = settings.resolved_provider()
    if provider == "anthropic":
        return AnthropicProvider(
            model=settings.model,
            effort=settings.effort,
            max_output_tokens=settings.max_output_tokens,
            refusal_fallback=settings.refusal_fallback,
        )
    if provider == "offline":
        return OfflineProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")


def build_cache(settings: Settings) -> AnswerCache:
    if settings.cache_backend == "redis":
        return RedisCache.from_url(settings.redis_url, settings.cache_ttl_seconds)
    if settings.cache_backend == "memory":
        return InMemoryCache(settings.cache_ttl_seconds)
    return NullCache()


def build_pipeline(settings: Settings, provider: LLMProvider | None = None) -> RAGPipeline:
    docs = load_documents(settings.corpus_dir)
    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    return RAGPipeline(
        index=BM25Index(chunks),
        provider=provider or build_provider(settings),
        cache=build_cache(settings),
        corpus_version=corpus_version(docs),
        top_k=settings.top_k,
        min_retrieval_score=settings.min_retrieval_score,
    )


def create_app(settings: Settings | None = None, pipeline: RAGPipeline | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = settings or Settings.from_env()
    pipeline = pipeline or build_pipeline(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    metrics = Metrics()

    app = FastAPI(
        title="Production RAG Service",
        version=__version__,
        description="Grounded answers with citations, cost tracking and guardrails.",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
        )
        return response

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "provider": pipeline.provider.name,
            "model": pipeline.provider.model,
            "chunks_indexed": len(pipeline.index.chunks),
            "corpus_version": pipeline.corpus_version,
            "cache_namespace": pipeline.cache_namespace,
        }

    @app.get("/v1/metrics")
    def get_metrics() -> dict:
        return metrics.snapshot()

    @app.post("/v1/query", response_model=QueryResponse)
    def query(body: QueryRequest, request: Request):
        allowed, retry_after = limiter.check(client_ip(request, settings.trusted_proxy_hops))
        if not allowed:
            metrics.record_rate_limited()
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Slow down and retry."},
                headers={"Retry-After": str(max(1, round(retry_after)))},
            )
        try:
            result = pipeline.answer(body.question)
        except LLMError as exc:
            metrics.record_error()
            logger.warning(
                json.dumps(
                    {
                        "event": "llm_error",
                        "request_id": request.state.request_id,
                        "retryable": exc.retryable,
                        "error": str(exc),
                    }
                )
            )
            raise HTTPException(
                status_code=503 if exc.retryable else 502,
                detail="The answer service is temporarily unavailable."
                if exc.retryable
                else "The answer service failed to process this request.",
            ) from exc

        metrics.record_answer(
            latency_ms=result.usage.latency_ms,
            cached=result.cached,
            abstained=result.abstained,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=result.usage.cost_usd,
        )
        logger.info(
            json.dumps(
                {
                    "event": "answer",
                    "request_id": request.state.request_id,
                    "model": result.usage.model,
                    "cached": result.cached,
                    "abstained": result.abstained,
                    "citations": len(result.citations),
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "cost_usd": result.usage.cost_usd,
                    "latency_ms": result.usage.latency_ms,
                }
            )
        )
        return result

    return app
