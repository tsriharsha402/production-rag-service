# Incident Response

This document defines incident severities and the process every team follows from detection to postmortem.

## Severity levels

- SEV1: a customer-facing outage affecting more than 25% of users, any data loss, or a confirmed security breach.
- SEV2: a major feature is degraded or unavailable for a subset of customers, with no data loss.
- SEV3: a minor issue with a workaround, or an internal tool outage.

When in doubt, declare the higher severity. Downgrading later is cheap; responding late is not.

## Roles

Every SEV1 and SEV2 has an incident commander (IC) who coordinates the response and does not debug. The IC assigns a communications lead, who owns customer and internal updates, and one or more responders.

## Declaring an incident

Declare an incident with the /incident command in Slack. This creates a channel named #inc-YYYYMMDD-short-name, pages the IC rotation for SEV1 and SEV2, and opens an incident record.

## Communication

For SEV1 incidents the communications lead updates the public status page at least every 30 minutes until resolution. For SEV2 incidents, updates go to the internal #incidents channel at least every hour.

## Postmortems

Every SEV1 and SEV2 requires a written postmortem within 5 business days of resolution. Postmortems are blameless: they focus on systems and decisions, not individuals. Each action item gets a single owner and a due date and is tracked in Jira with the label "postmortem". The engineering director reviews overdue postmortem action items every month.
