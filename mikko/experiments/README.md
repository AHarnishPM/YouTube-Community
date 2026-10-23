# Experiment ledger

Record each real run with: date, research question, dataset hash, split manifest,
annotation guideline version, code revision, model tag/digest, exact prompt,
threshold, hardware, latency, metrics, failure counts, reviewed errors and next decision.

Keep full outputs in `runs/`. Never compare methods on different examples without
explicitly accounting for the difference. Do not interpret fixture performance as
evidence. Write conclusions yourself after inspecting actual predictions.

Suggested experiments: keyword baseline; zero-shot LLM; train-only few-shot LLM;
target-only versus neighboring context; development-score threshold sweep.
Freeze one configuration before the held-out comparison.
