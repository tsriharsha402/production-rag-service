"""Answer generation providers.

Two implementations share one interface:

* ``AnthropicProvider`` - Claude, using search-result content blocks so every
  citation points at a retrieved chunk and quotes it verbatim.
* ``OfflineProvider`` - a deterministic extractive baseline. No API key, no cost,
  identical output on every run: this is what tests and CI use.

See docs/decisions/0002-provider-interface-with-offline-baseline.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from rag_service.documents import Chunk
from rag_service.retrieval import tokenize

ABSTAIN_MESSAGE = "I don't know based on the available documents."
REFUSAL_MESSAGE = "I can't help with that request."

SYSTEM_PROMPT = f"""You are an internal knowledge assistant. Employees ask questions and you \
answer using only the search results attached to their message.

- Ground every statement in the search results and cite them. Do not use outside knowledge.
- If the search results do not answer the question, reply with exactly "{ABSTAIN_MESSAGE}" \
followed by one sentence on what information is missing.
- Lead with the direct answer, then add only the details the employee needs to act on it.
- Keep answers under 120 words. Use plain sentences; no headings."""

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Generation:
    text: str
    # (index into the sources list, verbatim quoted text)
    citations: list[tuple[int, str]] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    abstained: bool = False
    refused: bool = False


class LLMError(Exception):
    """Generation failed. ``retryable`` tells the API whether to return 503 or 502."""

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, question: str, sources: list[Chunk]) -> Generation: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        max_output_tokens: int = 16000,
        refusal_fallback: bool = True,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.refusal_fallback = refusal_fallback and model in _FALLBACK_MODELS
        # The SDK already retries 408/409/429/5xx and connection errors with backoff.
        self._client = client or anthropic.Anthropic(timeout=60.0, max_retries=2)

    def build_request(self, question: str, sources: list[Chunk]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {
                "type": "search_result",
                "source": chunk.chunk_id,
                "title": f"{chunk.title} > {chunk.section}",
                "content": [{"type": "text", "text": chunk.text}],
                "citations": {"enabled": True},
            }
            for chunk in sources
        ]
        content.append({"type": "text", "text": question})
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "system": SYSTEM_PROMPT,
            "output_config": {"effort": self.effort},
            "messages": [{"role": "user", "content": content}],
        }
        if self.refusal_fallback:
            request["betas"] = [_FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    def generate(self, question: str, sources: list[Chunk]) -> Generation:
        request = self.build_request(question, sources)
        try:
            response = self._client.beta.messages.create(**request)
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            raise LLMError(f"Claude API temporarily unavailable: {exc}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(
                f"Claude API error {exc.status_code}: {exc.message}",
                retryable=exc.status_code >= 500,
            ) from exc

        usage = response.usage
        generation = Generation(
            text="",
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
        )
        if response.stop_reason == "refusal":
            generation.text = REFUSAL_MESSAGE
            generation.refused = True
            return generation

        parts: list[str] = []
        for block in response.content:
            if block.type != "text":
                continue  # thinking blocks, fallback markers
            parts.append(block.text)
            refs = []
            for citation in block.citations or []:
                if citation.type != "search_result_location":
                    continue
                generation.citations.append((citation.search_result_index, citation.cited_text))
                ref = citation.search_result_index + 1
                if ref not in refs:
                    refs.append(ref)
            if refs:
                parts.append("".join(f" [{ref}]" for ref in refs))
        generation.text = "".join(parts).strip()
        generation.abstained = generation.text.startswith(ABSTAIN_MESSAGE)
        return generation


class OfflineProvider:
    """Extractive baseline: return the retrieved sentence that best overlaps the question."""

    name = "offline"
    model = "offline-extractive"

    def __init__(self, min_overlap: int = 2) -> None:
        self.min_overlap = min_overlap

    def generate(self, question: str, sources: list[Chunk]) -> Generation:
        question_terms = set(tokenize(question))
        best: tuple[int, int, str] | None = None  # (overlap, -source_index, sentence)
        for index, chunk in enumerate(sources):
            for sentence in _sentences(chunk.text):
                overlap = len(question_terms & set(tokenize(sentence)))
                candidate = (overlap, -index, sentence)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate

        prompt_tokens = sum(len(chunk.text) for chunk in sources) // 4 + len(question) // 4
        if best is None or best[0] < self.min_overlap:
            return Generation(
                text=ABSTAIN_MESSAGE,
                model=self.model,
                input_tokens=prompt_tokens,
                output_tokens=len(ABSTAIN_MESSAGE) // 4,
                abstained=True,
            )
        overlap, neg_index, sentence = best
        index = -neg_index
        return Generation(
            text=f"{sentence} [{index + 1}]",
            citations=[(index, sentence)],
            model=self.model,
            input_tokens=prompt_tokens,
            output_tokens=len(sentence) // 4,
        )


def _sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [piece.strip(" -*") for piece in pieces if len(piece.strip()) > 20]
