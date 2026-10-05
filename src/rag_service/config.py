"""Runtime configuration, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    # "anthropic" calls Claude; "offline" uses a deterministic extractive baseline
    # that needs no API key (used for local demos, tests and CI).
    # "auto" picks "anthropic" when ANTHROPIC_API_KEY is set, otherwise "offline".
    llm_provider: str = "auto"
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    max_output_tokens: int = 16000
    refusal_fallback: bool = True

    corpus_dir: Path = Path("data/handbook")
    # 8 retrieves the answer-bearing section for 92.7% of answerable eval questions vs. 82.9%
    # at 4, for ~150 more input tokens. See docs/decisions/0005-retrieve-eight-chunks.md.
    top_k: int = 8
    # BM25 scores below this are treated as "no relevant document" and the
    # service abstains without paying for an LLM call.
    min_retrieval_score: float = 1.0

    cache_backend: str = "memory"  # "memory" | "redis" | "none"
    cache_ttl_seconds: int = 3600
    redis_url: str = "redis://localhost:6379/0"

    rate_limit_per_minute: int = 30
    # Number of trusted reverse proxies / load balancers in front of the service. 0 means
    # clients connect directly and X-Forwarded-For is ignored, since clients can forge it.
    trusted_proxy_hops: int = 0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            llm_provider=_env("LLM_PROVIDER", cls.llm_provider),
            model=_env("LLM_MODEL", cls.model),
            effort=_env("LLM_EFFORT", cls.effort),
            max_output_tokens=int(_env("LLM_MAX_OUTPUT_TOKENS", str(cls.max_output_tokens))),
            refusal_fallback=_env("LLM_REFUSAL_FALLBACK", "true").lower() == "true",
            corpus_dir=Path(_env("CORPUS_DIR", str(cls.corpus_dir))),
            top_k=int(_env("RETRIEVAL_TOP_K", str(cls.top_k))),
            min_retrieval_score=float(_env("RETRIEVAL_MIN_SCORE", str(cls.min_retrieval_score))),
            cache_backend=_env("CACHE_BACKEND", cls.cache_backend),
            cache_ttl_seconds=int(_env("CACHE_TTL_SECONDS", str(cls.cache_ttl_seconds))),
            redis_url=_env("REDIS_URL", cls.redis_url),
            rate_limit_per_minute=int(
                _env("RATE_LIMIT_PER_MINUTE", str(cls.rate_limit_per_minute))
            ),
            trusted_proxy_hops=int(_env("TRUSTED_PROXY_HOPS", str(cls.trusted_proxy_hops))),
        )

    def resolved_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "offline"
