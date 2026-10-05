# 0006: Daily spend cap that degrades gracefully

**Status:** Accepted (2026-10-05)

## Context

Per-client rate limiting stops one client from running up the bill, but not many clients at
once: a traffic spike, a script on many machines, or a launch that's more popular than
planned. Model spend scales with every request, and nothing bounded the total. The
playbook's [risk assessment](https://github.com/tsriharsha402/ai-delivery-playbook/blob/main/examples/handbook-assistant/03-risk-assessment.md)
listed this as risk R7: "no total daily spend cap".

## Decision

A daily budget in USD (`DAILY_BUDGET_USD`, default $10, `0` disables), enforced right before
every paid model call:

- **Degrade, don't go dark.** Cache hits and abstentions without a model call cost nothing,
  so they keep working after the cap. Only new paid answers are refused, with a 503, a
  clear message and `Retry-After` set to the seconds until midnight UTC.
- **Warn before the cap.** A `budget_warning` log event fires once per day when spend
  crosses 80%, so someone can act before users are affected.
- **Shared across replicas.** With `CACHE_BACKEND=redis`, spend is tracked with atomic
  `INCRBYFLOAT` on a per-day key, so replicas can't each spend the full budget.
- **Fail closed.** The service refuses to start with a budget set if the model has no known
  price, and answers from an unpriced fallback model are counted at the configured model's
  price, so nothing can bypass the cap silently.

## Consequences

- The worst-case daily bill is bounded: the budget plus at most one in-flight request per
  concurrent caller (spend is checked before a call and recorded after it).
- When the cap is hit, users with new questions get no answer until midnight UTC. That's
  deliberate for an internal assistant; a customer-facing product might prefer falling back
  to a cheaper model first.
- Spend is measured from the token usage the API returns, using `pricing.py`. If prices
  change and the table isn't updated, the cap drifts from the real bill, so the provider
  console's own spend limit should stay on as a second, independent backstop.

## Revisit when

- Daily spend regularly passes the 80% warning: raise the budget deliberately, or cut cost.
- The service becomes customer-facing: consider a cheaper fallback model instead of refusing.
