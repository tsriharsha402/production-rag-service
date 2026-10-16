# 0008: Prometheus metrics, a Grafana dashboard and tested alert rules

**Status:** Accepted (2026-10-15)

## Context

`/v1/metrics` counts events in the memory of the process that serves the request. That was
fine for a single process, but it breaks as soon as the service scales:

- With several uvicorn workers, each request for `/v1/metrics` lands on one worker and
  reports only that worker's share. Refresh twice and the numbers jump around.
- With several replicas, nothing adds the replicas up.
- Every restart or deploy resets the counts, so there is no history to compare a release
  against.

Nobody can alert on numbers like that, and the questions that matter for an AI service are
about trends: is the thumbs-down rate up since the last release, is cost per answer
creeping, are we about to hit the budget.

## Decision

1. **Prometheus is the source of truth.** `GET /metrics` exposes counters and histograms:
   answers by `cached`/`abstained`, answer latency, tokens and cost by model, model errors,
   rate-limit and budget rejections, and feedback votes. Prometheus stores the history and
   sums across replicas.
2. **Multiple workers per container** use `prometheus_client`'s multiprocess mode
   (`PROMETHEUS_MULTIPROC_DIR`): each worker writes to shared files and `/metrics` reads all
   of them, so the answer is the same whichever worker serves the scrape.
3. **State is read at scrape time, not counted.** Today's spend and the budget come from the
   budget store (Redis when shared), so every replica reports the shared total. Dashboards
   and alerts use `max()` for these, not `sum()`, which would count it once per replica.
   `rag_service_info` labels the version, model, corpus and cache namespace, so metrics
   can be compared before and after a change.
4. **Changed votes are counted with two monotonic counters**: votes and retractions. When
   someone changes a vote, the old rating is retracted and the new one counted, so
   `votes - retracted` is the current tally. Counters can't go down, and a gauge would be
   wrong across workers. The answer's previous rating is kept with the answer record in the
   feedback store, which Redis shares across replicas, so a vote changed on another replica
   still counts once.
5. **The dashboard and alerts live in the repo and are tested.** The Grafana dashboard and
   Prometheus alert rules are provisioned by `docker compose up`. CI runs
   `promtool check config` and `promtool test rules`. The alert unit tests include cases
   that must not fire, such as a high thumbs-down rate on too few votes, or one inflated by
   changed votes. A pytest check fails if the dashboard or alerts reference a metric the
   service doesn't export, so renaming a metric can't silently blank a panel or disable an
   alert.
6. **`/v1/metrics` stays** for the UI and quick checks without Prometheus, documented as
   per-process.

## Alerts

| Alert | Fires when | Severity |
|---|---|---|
| RagServiceDown | a replica can't be scraped for 2 min | page |
| RagHighErrorRate | > 5% of model calls fail for 5 min | page |
| RagBudgetExhausted | any question refused for budget in the last 10 min | page |
| RagBudgetStoreDown | the spend store can't be read for 5 min (the cap fails closed) | page |
| RagSlowAnswers | uncached p95 > 10 s for 10 min | warning |
| RagBudgetNearlySpent | > 80% of today's budget spent | warning |
| RagThumbsDownRateHigh | > 30% thumbs down over 6 h, with at least 20 votes | warning |

## Consequences

- Metrics survive restarts and add up across workers and replicas. Release comparisons use
  `rag_service_info`.
- A new dependency, `prometheus-client`, and two more containers in the local stack.
- Multiprocess mode needs an empty `PROMETHEUS_MULTIPROC_DIR` at startup, so stale files
  from the last run aren't counted again.
- Metrics now scale to several workers, but the in-memory answer cache, spend total and
  record of answers to rate are still per process. With several workers or replicas, use
  `CACHE_BACKEND=redis`. The service logs a `per_process_state` warning when multiprocess
  mode runs without it.
- The `model` label grows with each fallback model, which is a handful at most. Questions
  and answer ids are never labels, so cardinality stays bounded.

## Revisit when

- Tracing is needed to see where time goes inside a request (retrieval vs. model):
  OpenTelemetry, which is still on the roadmap.
- Alerts need routing (on-call schedules, Slack): add Alertmanager config.
