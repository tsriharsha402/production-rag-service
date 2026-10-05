# 0003: Exact-match answer cache before a semantic cache

**Status:** Accepted

## Context

Internal knowledge assistants get the same questions repeatedly, especially after an
announcement. Every repeated LLM call costs money and a few seconds of latency.

## Decision

Cache complete answers keyed on the normalized question (lowercased, whitespace and
trailing punctuation removed) plus a **cache namespace**: a hash of everything that can
change an answer, which is the corpus content, the model, the prompt version, the model
settings (effort, max output tokens) and the retrieval settings (top-k, minimum score).
In-memory LRU with a TTL for a single instance; Redis when running several replicas.

## Consequences

- Repeated questions are answered in milliseconds at zero cost.
- Editing a document, the prompt, or any model or retrieval setting changes the namespace,
  so answers produced under an old configuration are never served. `/healthz` reports the
  current namespace, so a deploy that should invalidate the cache can be checked.
- Refusals are never cached.
- Paraphrases ("PTO days per year?" vs. "How much vacation do I get?") miss the cache.

## Revisit when

Cache hit rate in production is low but question logs show many paraphrased repeats.
Then evaluate a semantic cache (embedding similarity above a tuned threshold), measuring
the rate of wrong cache hits, not just the hit rate.

## Revision (2026-10-05)

The first version keyed only on the corpus hash and the model, so changing the prompt,
effort or retrieval settings kept serving answers produced under the old configuration until
they expired (and across redeploys with Redis). The namespace now covers every setting that
affects an answer, and a test checks that changing each one starts a fresh cache.
