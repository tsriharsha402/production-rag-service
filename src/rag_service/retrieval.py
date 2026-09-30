"""BM25 lexical retrieval.

Deliberately dependency-free: no vector database to run, nothing to pay for,
and a strong baseline to measure future dense or hybrid retrieval against.
See docs/decisions/0001-start-with-bm25-retrieval.md.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from rag_service.documents import Chunk

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)


def tokenize(text: str) -> list[str]:
    tokens = []
    for token in _TOKEN.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        # Minimal plural folding ("rollbacks" -> "rollback") without a stemming library.
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        # Section headings and titles carry a lot of signal, so they are indexed with the body.
        self._docs = [tokenize(f"{c.title} {c.section} {c.text}") for c in chunks]
        self._tf = [Counter(tokens) for tokens in self._docs]
        self._lengths = [len(tokens) for tokens in self._docs]
        self._avg_len = sum(self._lengths) / max(len(self._lengths), 1)
        df: Counter[str] = Counter()
        for tokens in self._docs:
            df.update(set(tokens))
        n = len(chunks)
        self._idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def search(self, query: str, top_k: int = 4) -> list[ScoredChunk]:
        terms = tokenize(query)
        if not terms:
            return []
        scores = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * self._lengths[i] / self._avg_len)
            for term in terms:
                freq = tf.get(term)
                if freq:
                    score += self._idf[term] * freq * (self.k1 + 1) / (freq + norm)
            if score > 0:
                scores.append((score, i))
        scores.sort(key=lambda pair: (-pair[0], pair[1]))
        return [ScoredChunk(self.chunks[i], round(score, 4)) for score, i in scores[:top_k]]
