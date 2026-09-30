# 0003: Exact-match answer cache before a semantic cache

**Status:** Accepted

## Context

Internal knowledge assistants get the same questions repeatedly, especially after an
announcement. Every repeated LLM call costs money and a few seconds of latency.

## Decision

Cache complete answers keyed on the normalized question (lowercased, whitespace and
trailing punctuation removed), the model, and a hash of the corpus content. In-memory LRU
with a TTL for a single instance; Redis when running several replicas.

## Consequences

- Repeated questions are answered in milliseconds at zero cost.
- Editing any document changes the corpus hash, so stale answers are never served.
- Refusals are never cached.
- Paraphrases ("PTO days per year?" vs. "How much vacation do I get?") miss the cache.

## Revisit when

Cache hit rate in production is low but question logs show many paraphrased repeats.
Then evaluate a semantic cache (embedding similarity above a tuned threshold), measuring
the rate of wrong cache hits, not just the hit rate.
