"""The request path: cache -> retrieve -> (abstain early | generate) -> cite -> cache."""

from __future__ import annotations

import time

from rag_service.cache import AnswerCache, cache_key, cache_namespace
from rag_service.llm import ABSTAIN_MESSAGE, LLMProvider
from rag_service.pricing import cost_usd
from rag_service.retrieval import BM25Index
from rag_service.schemas import Citation, QueryResponse, RetrievedChunk, Usage


class RAGPipeline:
    def __init__(
        self,
        index: BM25Index,
        provider: LLMProvider,
        cache: AnswerCache,
        corpus_version: str,
        top_k: int = 4,
        min_retrieval_score: float = 1.0,
    ) -> None:
        self.index = index
        self.provider = provider
        self.cache = cache
        self.corpus_version = corpus_version
        self.top_k = top_k
        self.min_retrieval_score = min_retrieval_score

    @property
    def cache_namespace(self) -> str:
        # Computed on every call, so swapping the provider or changing retrieval settings
        # can never reuse answers produced under the old configuration.
        return cache_namespace(
            self.corpus_version,
            self.provider.fingerprint,
            f"top_k={self.top_k}",
            f"min_score={self.min_retrieval_score}",
        )

    def answer(self, question: str) -> QueryResponse:
        started = time.perf_counter()
        key = cache_key(question, self.cache_namespace)

        cached = self.cache.get(key)
        if cached is not None:
            response = QueryResponse.model_validate(cached)
            response.cached = True
            response.usage.latency_ms = _elapsed_ms(started)
            return response

        hits = [
            hit
            for hit in self.index.search(question, self.top_k)
            if hit.score >= self.min_retrieval_score
        ]
        retrieved = [
            RetrievedChunk(
                ref=i + 1,
                chunk_id=hit.chunk.chunk_id,
                doc_id=hit.chunk.doc_id,
                title=hit.chunk.title,
                section=hit.chunk.section,
                score=hit.score,
            )
            for i, hit in enumerate(hits)
        ]

        if not hits:
            # Nothing relevant was retrieved: abstain without paying for an LLM call.
            response = QueryResponse(
                answer=ABSTAIN_MESSAGE,
                abstained=True,
                cached=False,
                citations=[],
                retrieved=[],
                usage=Usage(
                    model=self.provider.model,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    latency_ms=_elapsed_ms(started),
                ),
            )
        else:
            sources = [hit.chunk for hit in hits]
            generation = self.provider.generate(question, sources)
            citations: list[Citation] = []
            seen: set[tuple[int, str]] = set()
            for index, quote in generation.citations:
                if not 0 <= index < len(sources) or (index, quote) in seen:
                    continue
                seen.add((index, quote))
                chunk = sources[index]
                citations.append(
                    Citation(
                        ref=index + 1,
                        chunk_id=chunk.chunk_id,
                        doc_id=chunk.doc_id,
                        title=chunk.title,
                        section=chunk.section,
                        quote=quote,
                    )
                )
            response = QueryResponse(
                answer=generation.text,
                abstained=generation.abstained,
                cached=False,
                citations=citations,
                retrieved=retrieved,
                usage=Usage(
                    model=generation.model,
                    input_tokens=generation.input_tokens,
                    output_tokens=generation.output_tokens,
                    cost_usd=(
                        0.0
                        if generation.model == "offline-extractive"
                        else cost_usd(
                            generation.model,
                            generation.input_tokens,
                            generation.output_tokens,
                            generation.cache_read_tokens,
                            generation.cache_write_tokens,
                        )
                    ),
                    latency_ms=_elapsed_ms(started),
                ),
            )
            if generation.refused:
                return response  # never cache refusals

        self.cache.set(key, response.model_dump())
        return response


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
