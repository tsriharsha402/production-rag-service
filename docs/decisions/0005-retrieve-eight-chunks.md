# 0005: Retrieve 8 chunks instead of 4

**Status:** Accepted (2026-10-05)

## Context

The first live evaluation with Claude passed 84.8% of questions. All 7 failures were
correct "I don't know" answers: the required fact wasn't in the 4 retrieved chunks. Doc-level
hit@k (95.1%) hid this, because in 5 of the 7 cases retrieval found the right document but the
wrong section. We added a stricter metric, **context recall** (does the text sent to the model
contain every required fact?), which was 82.9%.

## Options measured

[`evals/retrieval_experiment.py`](../../evals/retrieval_experiment.py), full results in
[`retrieval-experiment.md`](../../evals/results/retrieval-experiment.md):

| Variant | Context recall | Avg context tokens |
|---|---|---|
| Top 4 chunks (before) | 82.9% | ~170 |
| Top 6 chunks | 87.8% | ~245 |
| **Top 8 chunks** | **92.7%** | **~325** |
| Top 10 chunks | 95.1% | ~400 |
| Top 2 whole documents (parent-document retrieval) | 90.2% | ~480 |
| Top 3 whole documents | 92.7% | ~560 |

## Decision

Retrieve **8** chunks by default (`RETRIEVAL_TOP_K=8`).

- It matches the best whole-document variant's recall with about 40% less context, and
  needs no new code: it's one setting.
- **We did not pick 10**, even though it scores higher. Its only extra fix (`hard-05`) comes
  from a coincidental match on the word "code" in a chunk ranked 9th. Choosing it would be
  tuning to one test question, not improving retrieval.
- The 3 remaining misses (`hard-01`, `hard-05`, `hard-07`) share no vocabulary with their
  answers ("emailed… password" vs. "phishing", "login system" vs. "authentication", "taking
  pages" vs. "on-call rotation"). No keyword setting fixes them; semantic search does.

## Consequences

- About 150 more input tokens per question: roughly +$0.0006 per question on Opus 5.5 and
  +$0.0003 on Sonnet 5.5 at current prices. Output tokens still dominate the cost.
- More context means more irrelevant text alongside the answer. Grounded citations and the
  abstention rule limit the risk, but it must be confirmed with a live re-run.
- CI now gates on context recall ≥ 90%, so a chunking or retrieval change that hides answers
  can't merge silently.
- **Risk of overfitting:** the setting was chosen on the same 46 questions it's measured on.
  Mitigations: one general knob, the smallest value at which recall stops improving for
  real reasons, and every variant reported. Re-check when the evaluation set grows.

## Revisit when

- The live re-run shows more irrelevant citations or lower answer quality at 8 chunks.
- Semantic retrieval lands ([issue #2](https://github.com/tsriharsha402/production-rag-service/issues/2)):
  re-run the experiment, since hybrid ranking may need fewer chunks.
- The corpus grows enough that 8 chunks becomes a meaningful share of cost.
