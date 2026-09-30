# 0002: Provider interface with an offline baseline

**Status:** Accepted

## Context

Tests and CI should never depend on a paid API, a network connection or a secret. New
contributors should be able to run the whole system in minutes without an API key.
We also need a baseline: "Claude answers 90% of questions correctly" means little until
it is compared with something simpler.

## Decision

Answer generation sits behind a small `LLMProvider` interface with two implementations:

- `AnthropicProvider`: Claude, used in production.
- `OfflineProvider`: a deterministic extractive baseline that returns the retrieved
  sentence with the highest term overlap, or abstains.

`LLM_PROVIDER=auto` uses Claude when `ANTHROPIC_API_KEY` is set, and the offline baseline
otherwise.

## Consequences

- CI runs the full pipeline, including the evaluation quality gate, for free.
- The offline scores are a floor. Any LLM configuration has to beat them by a margin that
  justifies its cost.
- The offline baseline is intentionally weak on paraphrased and multi-part questions, so
  its scores should never be read as the product's quality.
