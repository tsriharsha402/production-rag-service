# On-Call Policy

Northwind Labs runs a follow-the-sun on-call model for every production service. This policy explains who is on call, how quickly pages must be answered and how on-call work is compensated.

## Rotation

Each team runs a weekly rotation that hands over every Monday at 10:00 local time. Every rotation has a primary and a secondary engineer. The outgoing primary runs a 15-minute handoff meeting covering open incidents, noisy alerts and risky deploys planned for the coming week.

Engineers join the rotation after completing their first 60 days and shadowing two full rotations. Nobody is scheduled for more than one week in four.

## Response times

Pages must be acknowledged within these targets:

- SEV1: acknowledge within 5 minutes, day or night.
- SEV2: acknowledge within 15 minutes.
- SEV3: handle on the next business day; no after-hours response required.

## Escalation

If a page is not acknowledged within 10 minutes it automatically escalates to the secondary. If it is still unacknowledged after 20 minutes it escalates to the team's engineering manager. Anyone can manually escalate to the incident commander rotation when an issue looks like a SEV1.

## Compensation

Primary on-call engineers receive a stipend of $500 per week; secondaries receive $250 per week. After any on-call week with more than three pages between 22:00 and 07:00, the primary takes a compensatory day off within the following two weeks.

## Alert hygiene

Every alert must link to a runbook. Alerts that fire more than five times in a week without requiring action are reviewed in the weekly handoff and either fixed, tuned or deleted.
