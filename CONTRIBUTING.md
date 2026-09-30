# Contributing

Thanks for helping improve this project.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install
```

## Before opening a pull request

```bash
make lint   # ruff check + format check
make test   # unit tests, no API key needed
make eval   # offline evaluation with the CI quality gate
```

## Changes to retrieval, prompts or models

Any change that can affect answer quality (chunking, retrieval, the system prompt,
the model or its settings) must include before/after evaluation results in the pull
request description. If the change warrants it, also run `make eval-live` against Claude
and attach the report from `evals/results/`.

Significant design choices get a short decision record in `docs/decisions/`.

## Good first issues

Issues labeled `good first issue` are scoped to a single module and include
acceptance criteria.
