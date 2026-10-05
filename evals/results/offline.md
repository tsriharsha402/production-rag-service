# Evaluation results: offline

46 questions (41 answerable, 5 deliberately unanswerable).

| Metric | Value |
|---|---|
| Retrieval hit@1 | 90.2% |
| Retrieval hit@k | 95.1% |
| Retrieval MRR | 0.917 |
| Answer keyword recall | 61.0% |
| Citation accuracy | 78.0% |
| False abstention rate | 17.1% |
| Abstention accuracy (unanswerable) | 80.0% |
| Overall pass rate | 63.0% |
| Total cost | $0.0000 |
| Avg cost per question | $0.00000 |
| Latency p50 / p95 | 0.3 ms / 0.5 ms |

## Failed cases

| Case | Question | Problem |
|---|---|---|
| oncall-02 | What happens if the primary doesn't respond to a page? | keyword recall 0% |
| incident-01 | What counts as a SEV1 incident? | keyword recall 0% |
| incident-03 | What is the deadline for writing a postmortem? | abstained on an answerable question |
| deploy-01 | Can I ship a change to production on a Friday? | keyword recall 0% |
| deploy-03 | What triggers an automatic rollback of a canary? | abstained on an answerable question |
| pto-01 | How many vacation days do I get each year? | keyword recall 0% |
| security-01 | How do I get access to production? | keyword recall 0% |
| security-02 | I lost my laptop. What should I do? | abstained on an answerable question |
| ai-01 | What do we need before changing the prompt of an AI feature in production? | keyword recall 0% |
| hard-01 | Someone emailed me asking for my password. Who should I tell? | abstained on an answerable question |
| hard-03 | My team keeps getting woken up by alerts that need no action. What is supposed to happen to them? | expected document not cited, keyword recall 0% |
| hard-04 | Is it okay to push a fix forward instead of reverting while things are on fire? | abstained on an answerable question |
| hard-05 | Who has to sign off on my code if I touch the login system? | expected document not retrieved, expected document not cited, keyword recall 0% |
| hard-06 | Can I ship a schema change in the same release as the code that uses it? | keyword recall 0% |
| hard-07 | When can a new hire start taking pages? | abstained on an answerable question |
| hard-08 | Do I have to tell customers when text was written by a model? | abstained on an answerable question |
| none-01 | What is the parental leave policy? | answered a question the documents cannot answer |
