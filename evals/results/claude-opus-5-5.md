# Evaluation results: claude-opus-5-5 (effort=medium)

46 questions (41 answerable, 5 deliberately unanswerable).

| Metric | Value |
|---|---|
| Retrieval hit@1 | 90.2% |
| Retrieval hit@k | 95.1% |
| Retrieval MRR | 0.917 |
| Answer keyword recall | 82.9% |
| Citation accuracy | 82.9% |
| False abstention rate | 17.1% |
| Abstention accuracy (unanswerable) | 100.0% |
| Overall pass rate | 84.8% |
| Total cost | $0.4288 |
| Avg cost per question | $0.00932 |
| Latency p50 / p95 | 3195.4 ms / 6295.5 ms |

## Failed cases

| Case | Question | Problem |
|---|---|---|
| oncall-02 | What happens if the primary doesn't respond to a page? | abstained on an answerable question |
| incident-01 | What counts as a SEV1 incident? | abstained on an answerable question |
| pto-01 | How many vacation days do I get each year? | abstained on an answerable question |
| hard-01 | Someone emailed me asking for my password. Who should I tell? | abstained on an answerable question |
| hard-05 | Who has to sign off on my code if I touch the login system? | abstained on an answerable question |
| hard-07 | When can a new hire start taking pages? | abstained on an answerable question |
| hard-08 | Do I have to tell customers when text was written by a model? | abstained on an answerable question |
