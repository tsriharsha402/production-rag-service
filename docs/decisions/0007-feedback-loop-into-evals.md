# 0007: User feedback feeds the evaluation set, through human review

**Status:** Accepted (2026-10-15)

## Context

The evaluation set gates every change in CI, but its 46 questions were written by the
team. Real users ask different questions, in different words, and the questions the
service gets wrong in production are exactly the ones a hand-written set misses. Without a
path from production back to the eval set, CI keeps passing while users keep hitting the
same failures.

## Decision

1. **Every response gets an `answer_id`**, cache hits included, and the API remembers what
   it served (question, answer, retrieved and cited sources) for a rating window
   (`FEEDBACK_WINDOW_SECONDS`, default 7 days).
2. **`POST /v1/feedback`** takes `answer_id`, `up`/`down` and an optional comment. The
   stored entry is built from the server's own record, never from the client, so feedback
   always reflects what the service actually answered. Unknown or expired ids get a 404.
   Votes are rate-limited per client in their own bucket, and the latest vote per answer
   wins, so changing a vote or adding a comment never double-counts.
3. **Storage follows the cache backend.** With Redis, answers are expiring keys and
   feedback an append-only list, shared across replicas. Otherwise feedback is appended
   to a JSONL file (`FEEDBACK_PATH`).
4. **Thumbs-down votes become eval candidates, never eval cases directly.**
   `evals/feedback_to_eval.py draft` groups them by question, drops ones the dataset
   already covers, ranks by number of complaints and adds a triage hint (retrieval miss,
   over-cautious generation, or a correct abstention the user disliked). A person sets
   `answerable`, `expected_doc` and `expected_keywords`; `promote` validates them against
   the corpus and appends them to `evals/dataset.jsonl`.
5. **Thumbs-down rate is a service metric** in `/v1/metrics` and the UI, next to cost and
   latency.

## Why a human in the loop

A thumbs down says something went wrong, not what right looks like. Auto-promoting
feedback would put unlabeled or mislabeled cases into the CI gate, and a user who dislikes
a correct "I don't know" would teach the gate to reward guessing. Labeling a case takes a
reviewer a minute or two; a wrong label costs every future change.

## Consequences

- The eval set grows from real failures, most-complained-about first, and every promoted
  case is a regression test for a problem a user actually hit.
- Feedback contains users' questions and comments. It is not exposed over the API; reading
  it needs access to the file or Redis. A real deployment needs a retention period and the
  same access controls as other user data. `var/` and `evals/candidates.jsonl` are
  git-ignored for the same reason.
- The JSONL backend is single-node, and it keeps the record of served answers in memory:
  after a restart, answers served before it can no longer be rated (404). Votes already
  recorded are on disk and kept. Running several replicas needs `CACHE_BACKEND=redis` or a
  database.
- Promoted cases can lower the CI pass rate. That is the point: the gate thresholds should
  be revisited deliberately, not lowered to make a new real failure pass.

## Revisit when

- Volume makes reviewing every thumbs-down impractical: sample by triage category, or
  pre-label with an LLM and keep human sign-off.
- Thumbs-down rate rises after a release: compare by `cache_namespace`, which identifies
  the corpus, model and retrieval settings each answer came from.
