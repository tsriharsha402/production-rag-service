# Code Review Guidelines

Code review keeps quality high and spreads knowledge across the team. These are the rules every repository follows.

## Approvals

Every pull request needs at least one approval from an engineer other than the author. Changes to payments, authentication or authorization code need two approvals, one of them from a code owner of that area.

## Pull request size

Keep pull requests under 400 changed lines. Larger changes should be split into a stack of smaller pull requests or discussed with the reviewer before review starts.

## Review turnaround

Reviewers respond within one business day, either with a review or with an estimate of when they will get to it. Authors should not wait more than one business day without hearing back.

## Before merging

Continuous integration must be green before merging. The author merges their own pull request after approval, and uses squash merges with a commit message that follows the Conventional Commits format.

## Tone

Review the code, not the person. Prefix optional suggestions with "nit:" so the author knows they are not blocking.
