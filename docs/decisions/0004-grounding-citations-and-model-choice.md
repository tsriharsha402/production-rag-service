# 0004: Grounded answers with native citations; model defaults

**Status:** Accepted

## Context

For an internal policy assistant, a confident wrong answer is worse than no answer:
people act on it. Users need to verify answers quickly, and the service must be honest
when the documents do not cover a question.

## Decision

1. **Native citations.** Retrieved chunks are sent to Claude as `search_result` content
   blocks with citations enabled. Every citation the API returns points to a specific
   chunk and quotes it verbatim, so citations can be verified rather than trusted.
2. **Abstain instead of guessing.** The system prompt requires a fixed abstention
   sentence when the search results do not answer the question. If retrieval finds
   nothing above `RETRIEVAL_MIN_SCORE`, the service abstains without calling the model
   at all.
3. **Model defaults.** `claude-opus-5-5` at `effort=medium`, set explicitly and
   configurable per deployment through `LLM_MODEL` and `LLM_EFFORT`. The server-side
   refusal fallback (`fallbacks: "default"`) is enabled so a false-positive safety
   decline is retried on a fallback model instead of failing the request.

## Consequences

- Every answer is auditable, and abstentions are measurable in the evaluation suite
  (abstention accuracy and false abstention rate).
- Opus is the most expensive option for a Q&A workload. The companion project
  [llm-model-selection](https://github.com/tsriharsha402/llm-model-selection) measures whether `claude-sonnet-5-5` or `claude-haiku-4-5`
  holds quality on this evaluation set at lower cost and latency. Switching is a
  configuration change, not a code change.
