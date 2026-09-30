# 0001: Start with BM25 lexical retrieval

**Status:** Accepted

## Context

Most RAG tutorials start with an embedding model and a vector database. That adds
infrastructure to run, an embedding bill, and a second model whose behavior has to be
understood, before we know whether retrieval quality is the problem at all.

## Decision

Ship v0.1 with BM25 over section-aware chunks, implemented in about 60 lines of
dependency-free Python. Measure it with the evaluation suite before adding anything else.

## Consequences

- Zero infrastructure, zero retrieval cost, fully deterministic results in CI.
- On the current evaluation set BM25 retrieves the right document for 95% of answerable
  questions and ranks it first for 90%. The misses are paraphrases with no shared
  vocabulary: "login system" vs. "authentication", "taking pages" vs. "on-call rotation".
  Those are exactly the cases dense retrieval handles well.

## Revisit when

- The paraphrase misses start to matter to users: add hybrid retrieval (BM25 + embeddings
  with reciprocal rank fusion) stored in PostgreSQL with pgvector, and keep it only if
  hit@1 improves on the evaluation suite.
- The corpus outgrows a single in-memory index (roughly 100k+ chunks).
