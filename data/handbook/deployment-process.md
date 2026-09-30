# Deployment Process

Every production change ships through the same pipeline so that deploys are boring, observable and reversible.

## Deploy windows

Standard deploys are allowed Monday to Thursday between 09:00 and 16:00 local time. Friday deploys are not allowed unless the change is a hotfix approved by an engineering manager. A company-wide change freeze runs from December 15 to January 5; during the freeze only approved hotfixes ship.

## Canary releases

Every deploy starts as a canary serving 5% of traffic for 30 minutes. The pipeline automatically rolls back the canary if the error rate exceeds 2% or if p95 latency rises more than 30% above the previous version's baseline. Only after the canary passes does the deploy continue to 100% of traffic.

## Feature flags

User-facing changes must ship behind a feature flag. Flags are removed within 30 days of reaching 100% rollout so that flag debt does not build up.

## Rollbacks

Any engineer may roll back their own deploy at any time without approval. Rolling back is always preferred to fixing forward during an incident.

## Database migrations

Schema migrations must be backward compatible with the currently running version, and are deployed separately from the application code that depends on them.
