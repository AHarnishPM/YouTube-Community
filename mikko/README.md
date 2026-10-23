# YouTube Community — Mikko claim detection

Claim detection and evaluation for the CS 4701 Community Notes project.
See the [AI assistance record](docs/AI_ASSISTANCE.md) for code provenance.
Run commands below from the `mikko/` directory.

The baseline and CLI use Python 3.11+ and the standard library. Run from this folder:

```bash
python3 -m unittest discover -s tests -v
python3 -m claim_detection predict data/examples/claims.jsonl --output experiments/demo-predictions.jsonl
python3 -m claim_detection evaluate data/examples/claims.jsonl --output experiments/runs/rules-demo
```

Every example is synthetic and invented for software checks. Its labels and metrics
are not research evidence. Outputs refuse overwrite; use new names for new runs.

## Local LLM

```bash
ollama serve
# In another terminal, if the model is not already downloaded:
ollama pull llama3.2:3b
python3 -m claim_detection evaluate data/examples/claims.jsonl --detector ollama --output experiments/runs/ollama-demo
```

Model downloads can be large. Set `OLLAMA_URL` for a different local inference host;
use `--model` in the CLI and `OLLAMA_MODEL` for the API. Inference has a 90-second
timeout per segment. Failures abort the run without generating misleading metrics.
Keep the API on localhost during development.

## Real data workflow

### Ready-to-label pilot

A local pilot was prepared at `data/raw/ocw-pilot-v2/pilot-unlabeled.jsonl`:
60 unlabeled windows sampled from three MIT OCW lectures (20 per video). The full
407 windows, original VTT captions, source URLs, attribution, and checksums are in
the same local directory. Raw captions, prepared data, labels and run outputs
are excluded from Git; rebuild the pilot with the importer below. Subjects: linear algebra, psychology, and biology. See
`manifest.json` for exact videos and caption sources. These are real transcripts,
not synthetic examples. No human labels or research accuracy results exist yet.

This is a lecture-only convenience sample for refining guidelines and debugging.
Do not claim it represents general YouTube content; expand to podcasts, interviews,
reviews and tutorials before the main comparison. Keep pilot videos out of the
future confirmatory test set, including any windows not selected in the pilot.
Caption cleanup/windowing are adaptations; MIT OCW attribution and the linked
CC BY-NC-SA 4.0 notice are retained. Check the original sources if redistributing data.

After writing your annotation guidelines, begin with:

```bash
python3 -m claim_detection.annotate label data/raw/ocw-pilot-v2/pilot-unlabeled.jsonl --journal data/labeled/mikko-pilot.jsonl --annotator mikko --guidelines data/annotation-guidelines.txt
```

Use a second independent journal on the same 60 windows for agreement checking.
Label independently before inspecting model predictions to avoid bias.

To reproduce the pilot path used in the labeling example, run
`python3 -m claim_detection.corpus data/ocw-pilot-sources.json --output data/raw/ocw-pilot-v2`.
Rebuild into a new directory with the optional network importer (requires system curl):

```bash
python3 -m claim_detection.corpus data/ocw-pilot-sources.json --output data/raw/ocw-pilot-new
```

If Aaron supplies raw captions instead of coherent windows, normalize one video's
JSON export with the preparation command:

```bash
python3 -m claim_detection.prepare data/examples/captions.json --output data/prepared/demo.jsonl
```

Input shape is shown in `data/examples/captions.json`. The algorithm waits for a
sentence ending after 20 seconds, caps windows at 40 seconds, and splits gaps over
3 seconds. These are configurable starting heuristics, not validated choices.
Caption boundaries are preserved; partial sentences can remain at a hard limit.
Source indices are retained and IDs depend on video, times and text, so changed
transcripts cannot accidentally reuse old annotations. It neither fetches transcripts
nor invents timestamps. Review windows before freezing segmentation for experiments.

For human labeling, first write your own annotation guidelines in a local text file,
then run the blind terminal workflow against real prepared windows:

```bash
python3 -m claim_detection.annotate label data/prepared/real.jsonl --journal data/labeled/mikko-journal.jsonl --annotator mikko --guidelines data/annotation-guidelines.txt
python3 -m claim_detection.annotate export data/prepared/real.jsonl --journal data/labeled/mikko-journal.jsonl --annotator mikko --guidelines data/annotation-guidelines.txt --output data/labeled/claims.jsonl
```

Each answer saves immediately; quit and rerun to resume. Existing labels and model
predictions are hidden. Use a separate journal for a second annotator. Exports require
complete boolean labels; `unsure` cases remain blocked for human adjudication. The
current tool does not implement an adjudication interface: retain the original journal
and create a fresh adjudicated journal after resolving disagreements. Dataset and
guideline hashes prevent accidentally resuming against changed inputs.

Compare two independently completed journals to identify disagreements:

```bash
python3 -m claim_detection.agreement data/labeled/mikko-journal.jsonl data/labeled/second-journal.jsonl --output experiments/annotation-agreement.json
```

This computes raw agreement and Cohen's kappa on definite label pairs and lists
every disagreement or uncertain pair for review. It requires distinct annotators,
matching dataset/guideline hashes and identical ID coverage. An undefined kappa is
reported as null; uncertain pairs are counted separately, never silently discarded.

Aaron exports one coherent window per JSONL row. Required keys: `segment_id`,
`video_id`, `start`, `end`, `text`. Seconds must satisfy `0 <= start < end`.
IDs must stay stable when results are joined back to transcripts.

For evaluation add `label` (human-reviewed JSON boolean), `category`, and `split`.
Optional annotation metadata: `annotator`, `rationale`, `guideline_version`,
`adjudicated_by`, `source_url`, `caption_source`. Do not commit private raw data.

```bash
python3 -m claim_detection split data/labeled/claims.jsonl --output data/labeled/claims-split.jsonl
python3 -m claim_detection evaluate data/labeled/claims-split.jsonl --split dev --output experiments/runs/rules-dev-v1
python3 -m claim_detection evaluate data/labeled/claims-split.jsonl --detector ollama --split dev --model-digest YOUR_DIGEST --output experiments/runs/llama-dev-v1
# Only after freezing the configuration:
python3 -m claim_detection evaluate data/labeled/claims-split.jsonl --detector ollama --split test --allow-test --output experiments/runs/llama-test-v1
```

Split allocation is seeded 60/20/20 by video (approximate for small corpora), not
stratified. Inspect class/category coverage yourself. The runner rejects leakage
present in the file; it cannot detect an external few-shot prompt containing test data.
Use `--prompt-file path/to/prompt.txt` for an experimental prompt. Runs save predictions,
overall/category metrics, input and prompt hashes, prompt text, timestamp and latency.
Record code revision, hardware and model digest in the experiment ledger too.
New Ollama evaluation runs automatically query the installed model digest and details,
save hashes of the Python source files, and reject a mismatched `--model-digest`.

Audit the dataset before experiments and select thresholds using saved development
scores (no new model calls):

```bash
python3 -m claim_detection.research audit data/examples/claims.jsonl --output experiments/fixture-audit.json
python3 -m claim_detection.research sweep experiments/runs/rules-demo --output experiments/fixture-thresholds.json
```

The audit reports split sizes, label counts, categories and duplicate text across
splits. Threshold selection refuses test runs and chooses maximum development F1,
breaking ties by precision and then higher threshold. Fix that objective before real
experiments. These commands do not establish label quality or real-world accuracy.
Older runs missing per-prediction split metadata must be regenerated under a new name.

## Backend integration

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[api,test]'
.venv/bin/python -m uvicorn claim_detection.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the generated API interface. Aaron can instead
import `claim_detection.api.router` and mount it in the team app.
The generated `data/examples/openapi.json` is a shareable machine-readable contract
for Aaron and Kenza; regenerate it from `app.openapi()` after changing API models.

`requirements-lock.txt` records the versions tested on Python 3.13/macOS. To reproduce
that environment, install `-r requirements-lock.txt` before installing the editable
package. Run `.venv/bin/python -m unittest discover -s tests -v` to include API tests.
All 30 tests passed at the latest verification. Unit tests mock Ollama responses.
A separate live smoke test completed four synthetic examples with the installed
Llama 3.1 8B Q4_0 model. Its local run outputs are excluded from Git.
This confirms local inference works, not real-data accuracy. The proposal's Llama 3.2
model has not been verified by these changes; the default remains `llama3.2:3b`.

```bash
curl http://127.0.0.1:8000/v1/claims/detect -H 'Content-Type: application/json' --data-binary @data/examples/request.json
```

The response contains `schema_version` and ordered `predictions`. Each prediction
preserves the input fields and includes `is_context_worthy`, `confidence`, `reason`,
`detector`, `threshold`. `confidence` always means positive-class score, even for a
negative result, and is not calibrated. Invalid inputs return 422; invalid/unavailable
Ollama returns 503. Batches are all-or-nothing with a maximum of 32 segments. For long
videos use small batches or a background job owned by the platform.

## Structure

```text
claim_detection/
  core.py          validated segment and detector interfaces
  prepare.py       caption exports to stable transcript windows
  corpus.py        attributed MIT OCW caption importer and pilot sampler
  annotate.py      blind, resumable human-labeling journal and export
  agreement.py     independent annotator agreement and review list
  detectors.py     rule baseline and structured Ollama adapter
  evaluation.py    video splits, metrics, prediction persistence
  research.py      dataset audit and cached development threshold sweep
  __main__.py      predict / split / evaluate commands
  api.py           optional FastAPI router and local app
data/examples/     synthetic software fixtures only
tests/             offline logic, failure and API contract checks
experiments/       ledger and ignored run outputs
docs/              internal plan and assistance record
```

Future chapters and sponsors should be sibling packages with their own interval
schemas, labels, detectors and evaluation. Do not overload claim confidence to mean
ad likelihood or chapter quality. Ingestion, database, extension and retrieval are
teammate-owned and intentionally external to this module.

Implementation references: [Ollama chat API](https://docs.ollama.com/api/chat),
[structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[FastAPI request bodies](https://fastapi.tiangolo.com/tutorial/body/).
