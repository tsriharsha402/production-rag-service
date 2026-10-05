# Retrieval experiment

41 answerable questions from `evals/dataset.jsonl`. Context size is estimated at 4 characters per token.

| Variant | Context recall | Avg context tokens | Questions still missing the answer |
|---|---|---|---|
| top 4 chunks | 34/41 (82.9%) | 171 | oncall-02, incident-01, pto-01, hard-01, hard-05, hard-07, hard-08 |
| top 6 chunks | 36/41 (87.8%) | 244 | oncall-02, incident-01, hard-01, hard-05, hard-07 |
| top 8 chunks | 38/41 (92.7%) | 324 | hard-01, hard-05, hard-07 |
| top 10 chunks | 39/41 (95.1%) | 397 | hard-01, hard-07 |
| top 12 chunks | 39/41 (95.1%) | 450 | hard-01, hard-07 |
| top 1 whole document(s) | 37/41 (90.2%) | 267 | hard-01, hard-04, hard-05, hard-07 |
| top 2 whole document(s) | 37/41 (90.2%) | 482 | hard-01, hard-04, hard-05, hard-07 |
| top 3 whole document(s) | 38/41 (92.7%) | 561 | hard-01, hard-05, hard-07 |
