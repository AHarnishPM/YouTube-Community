# Bugs found and fixed — retrieval component

Found by deliberately probing the weakest parts of the pipeline on 2026-10-22/23.
All eight are fixed; the suite went from 11 to 48 tests.

Run everything below from `CS 4701/YouTube-Community`.

| # | Bug | Severity | Why it mattered |
|---|---|---|---|
| [1](#bug-1) | `--pinned` rebuild returned raw wikitext, not article text | **critical** | silently destroyed the reproducibility guarantee |
| [2](#bug-2) | Subsections of "References" leaked into the index | **high** | citation lists indexed as evidence |
| [3](#bug-3) | BM25 returned zero-score passages as evidence | medium | handed the generator unrelated text to cite |
| [4](#bug-4) | Hybrid silently capped results below the requested `k` | medium | would make recall@k read short |
| [5](#bug-5) | Empty claim retrieved "evidence" instead of erroring | low | noise presented as results |
| [6](#bug-6) | Saving an empty index produced an unloadable one | low | error blamed the read, not the write |
| [7](#bug-7) | Impossible chunk-size config yielded nothing, silently | low | looked like "the article had no text" |
| [8](#bug-8) | `label` crashed on Ctrl-D and **lost every judgement** | **high** | hours of irreplaceable human work |

Verify the whole set at once:

```bash
./.venv/bin/python -m pytest tests/ -q        # 48 passed
```

Bugs 6 and 7 were found in a second pass, after the eval harness was added. Both share
the shape of the original truncation bug: **a silent empty result where an error belonged.**

---

<a name="bug-1"></a>
## Bug 1 — `--pinned` returned wikitext instead of article text

**Severity: critical.** This broke the single guarantee the pinning design existed to provide.

### Symptom

`build --pinned` was supposed to re-fetch the exact revisions recorded in the manifest, so an
experiment could be reproduced months later. It instead fetched a completely different format
of the same article.

### Reproduce it

This is still live — the behaviour is Wikipedia's API, not our code, so it reproduces today:

```bash
./.venv/bin/python - <<'EOF'
import requests
S = requests.Session()
S.headers.update({"User-Agent": "CS4701-demo (kd497@cornell.edu)"})
API = "https://en.wikipedia.org/w/api.php"

# How we fetch normally: the plaintext extract
a = S.get(API, params={"action":"query","prop":"extracts","titles":"Paris Agreement",
    "explaintext":"1","format":"json","formatversion":"2"}).json()
plain = a["query"]["pages"][0]["extract"]

# How the old --pinned path fetched a specific revision
rev = S.get(API, params={"action":"query","prop":"revisions","titles":"Paris Agreement",
    "rvprop":"ids","format":"json","formatversion":"2"}).json()
rid = rev["query"]["pages"][0]["revisions"][0]["revid"]
b = S.get(API, params={"action":"query","prop":"revisions","revids":str(rid),
    "rvprop":"ids|content","rvslots":"main","format":"json","formatversion":"2"}).json()
wiki = b["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]

print(f"plaintext extract : {len(plain):>8,} chars | {plain[:70]!r}")
print(f"revision content  : {len(wiki):>8,} chars | {wiki[:70]!r}")
print(f"same text? {plain == wiki}")
EOF
```

Observed:

```
plaintext extract :   38,142 chars | 'The Paris Agreement (also called the Paris Accords...'
revision content  :  119,907 chars | '{{Short description|2015 international treaty regar...'
same text? False
```

**38,142 characters of clean prose versus 119,907 of `{{templates}}` and `[[links]]`.** A
`--pinned` rebuild would have indexed markup.

### A second trap underneath it

The obvious fix — ask `extracts` for a revision id — **fails silently**:

```bash
./.venv/bin/python - <<'EOF'
import requests
S = requests.Session(); S.headers.update({"User-Agent": "CS4701-demo (kd497@cornell.edu)"})
API = "https://en.wikipedia.org/w/api.php"
old = 1378148547          # the revision in our manifest
r = S.get(API, params={"action":"query","prop":"extracts","revids":str(old),
    "explaintext":"1","format":"json","formatversion":"2"}).json()
cur = S.get(API, params={"action":"query","prop":"extracts","titles":"Paris Agreement",
    "explaintext":"1","format":"json","formatversion":"2"}).json()
e1 = r["query"]["pages"][0].get("extract","")
e2 = cur["query"]["pages"][0].get("extract","")
print(f"asked for revision {old}, got {len(e1):,} chars")
print(f"identical to TODAY's text? {e1 == e2}")
print(f"warnings: {r.get('warnings')}")
EOF
```

Observed: `identical to TODAY's text? True`, with **no warning**. The API accepts the
revision id and ignores it.

### Root cause

`explaintext` comes from the TextExtracts extension, which only serves an article's
**current** revision. There is no plaintext-at-revision endpoint. The original design assumed
the corpus could be regenerated from pinned revision IDs — **that assumption was simply false.**

### Fix

Stop pretending it is possible:

- **Removed** the `revision_id` parameter from `fetch_article` entirely. A parameter that
  returns a different content format is worse than no parameter.
- **The committed corpus text is now the reproducible artifact.** `data/corpus/articles.jsonl`
  (324K) is committed rather than gitignored. It is the only thing that preserves the pinned text.
- **`build --pinned` now reuses that committed text** instead of re-fetching.
- **The manifest's job changed** from *regenerate* to *detect drift* — new `check_drift()` and
  a `drift` command report which articles have moved since the corpus was built.

### Verify the fix

```bash
./.venv/bin/python -m rag.cli build --pinned
#   reusing 7 articles from the committed corpus (no re-fetch; revisions preserved)

./.venv/bin/python -m rag.cli drift
#   reports which pinned revisions have changed on Wikipedia since we fetched
```

Guarded by `tests/test_retrieve.py::test_fetch_article_cannot_be_asked_for_a_revision`, which
asserts the parameter stays gone.

---

<a name="bug-2"></a>
## Bug 2 — subsections of skipped sections leaked into the index

**Severity: high.**

### Symptom

The chunker drops navigation sections (`References`, `External links`, `See also`, …) because
they are bookkeeping, not evidence. But a **subsection** of one was kept.

### Reproduce it

```bash
./.venv/bin/python - <<'EOF'
from rag.corpus.chunk import _parse_paragraphs
text = ("== Real ==\nkeep keep keep\n"
        "== References ==\ndrop drop drop\n"
        "=== Cited works ===\nleak leak leak")
for p in _parse_paragraphs(text):
    print(f"  section={p.section!r:16} text={p.text!r}")
EOF
```

**Before the fix**, `=== Cited works ===` appeared in the output. **Now** only `Real` survives.

### Root cause

`_parse_paragraphs` tracked only the *current section name* and compared it against the skip
list. On reaching `=== Cited works ===` the tracker overwrote `References` with `Cited works`,
which is not in the list — so skipping stopped.

Real Wikipedia articles do exactly this: `== References ==` with `=== Citations ===`,
`=== Sources ===`, `=== Bibliography ===` beneath it.

### Why it mattered beyond tidiness

Citation lists are **dense with proper nouns, dates and titles** — precisely the tokens that
score well on entity-heavy claims. So the leaked passages would not have sat harmlessly at
the bottom of results; they would have competed near the top, and a note could have cited a
bibliography entry as evidence.

### Fix

Skipping is now **depth-aware**. Entering a skipped heading records its level; everything is
dropped until a heading at the same or shallower level closes the region.

### Verify the fix

```bash
./.venv/bin/python -m pytest tests/test_chunk.py -q -k "subsection or skipped_region"
```

Visible in the data too: the corpus went from **458 to 457 passages** after the fix — that
removed passage was the leak.

---

<a name="bug-3"></a>
## Bug 3 — BM25 returned zero-score passages as evidence

**Severity: medium.**

### Symptom

Query the lexical retriever with terms absent from the entire corpus and it still returned
`k` passages, each scoring exactly `0.000`.

### Reproduce it

```bash
./.venv/bin/python - <<'EOF'
from pathlib import Path
from rag.store.numpy_store import NumpyVectorStore
from rag.retrieve import BM25Retriever
store = NumpyVectorStore.load(Path("data/index"))
bm25 = BM25Retriever(store.passages)
hits = bm25.retrieve("zzzxqv flurble wumpus", 3)
print(f"hits: {len(hits)}")
for h in hits:
    print(f"  score={h.score:.3f}  {h.passage.title}")
EOF
```

**Before:** 3 hits, every score `0.000`. **Now:** 0 hits.

### Root cause

The retriever sorted by score and sliced the top `k` without checking whether the score meant
anything. BM25 returns 0 when **no query term appears in the passage at all**.

This is different from dense retrieval, where "irrelevant" is a fuzzy judgement about
distance (hence D-09). For BM25 it is **exact**: zero means zero lexical connection. There is
no reason to guess.

### Fix

Drop hits with `score <= 0` rather than padding the result to `k`. Returning fewer than `k`
is the honest answer.

### Verify the fix

```bash
./.venv/bin/python -m pytest tests/test_retrieve.py -q -k zero_score
```

---

<a name="bug-4"></a>
## Bug 4 — hybrid silently returned fewer results than requested

**Severity: medium.** Dangerous specifically because it was silent and would have corrupted
an evaluation number.

### Symptom

Ask the hybrid retriever for 99 results and get 60, with no warning.

### Reproduce it

```bash
./.venv/bin/python - <<'EOF'
from pathlib import Path
from rag.store.numpy_store import NumpyVectorStore
from rag.retrieve import DenseRetriever, BM25Retriever, HybridRetriever
store = NumpyVectorStore.load(Path("data/index"))
d = DenseRetriever(store); b = BM25Retriever(store.passages)
h = HybridRetriever(d, b)                 # default pool = 50
print(f"asked for 99, got {len(h.retrieve('the paris agreement', 99))}")
EOF
```

**Before:** `asked for 99, got 60`. **Now:** 99.

### Root cause

`HybridRetriever` fused two candidate runs of `pool` results each (default 50). Their union
caps at `2 × pool` and is smaller wherever the retrievers agree — so any `k` above `pool` was
silently truncated.

### Why it mattered

This is our own D-03 reasoning turned against us. Evaluating **recall@k** for larger `k` would
have silently measured a short list, and the shortfall would have looked like a *retrieval
failure* rather than a plumbing bug — leading to wrong conclusions in the report.

### Fix

Widen the candidate pool to `max(pool, k)` per query.

### Verify the fix

```bash
./.venv/bin/python -m pytest tests/test_retrieve.py -q -k pool
```

---

<a name="bug-5"></a>
## Bug 5 — an empty claim retrieved "evidence"

**Severity: low**, but the fix is free.

### Symptom

Passing an empty string returned results, with a dense top score of `0.136`.

### Reproduce it

```bash
./.venv/bin/python - <<'EOF'
from pathlib import Path
from rag.store.numpy_store import NumpyVectorStore
from rag.retrieve import DenseRetriever
store = NumpyVectorStore.load(Path("data/index"))
d = DenseRetriever(store)
try:
    hits = d.retrieve("", 3)
    print(f"returned {len(hits)} hits, top score {hits[0].score:.3f}")
except ValueError as e:
    print(f"ValueError: {e}")
EOF
```

**Before:** `returned 3 hits, top score 0.136`. **Now:** `ValueError: empty claim`.

### Root cause

An empty string still produces a valid 384-dimensional vector, and dense search dutifully
returns its nearest neighbours. Nothing anywhere checked that the input was meaningful.

### Fix

All three retrievers validate the claim and raise `ValueError` on empty or whitespace-only
input. An empty claim is a caller bug — failing loudly beats returning noise that the
generator would cite.

### Verify the fix

```bash
./.venv/bin/python -m pytest tests/test_retrieve.py -q -k empty_claim
```

---

<a name="bug-6"></a>
## Bug 6 — saving an empty index produced an unloadable index

**Severity: low**, but it misdirects whoever hits it.

### Symptom

`save()` on a store with no passages wrote `passages.jsonl` and no `vectors.npy`. The
subsequent `load()` then failed with `no saved index in <dir>` — blaming the read for a
write that had silently half-succeeded.

### Reproduce it

```bash
./.venv/bin/python - <<'EOF'
import tempfile
from pathlib import Path
from rag.store.numpy_store import NumpyVectorStore
with tempfile.TemporaryDirectory() as td:
    try:
        NumpyVectorStore().save(Path(td))
        print("saved; files:", [p.name for p in Path(td).iterdir()])
        NumpyVectorStore.load(Path(td))
    except Exception as e:
        print(f"{type(e).__name__}: {e}")
EOF
```

**Before:** save succeeded, load raised `FileNotFoundError: no saved index`.
**Now:** save raises `ValueError: refusing to save an empty index`.

### Why it mattered

An empty index is always a symptom of something upstream — every fetch failed, or chunking
produced nothing (bug 7). Failing at the write names the real problem; failing at the read
sends you looking in the wrong file.

### Verify

```bash
./.venv/bin/python -m pytest tests/test_retrieve.py -q -k empty_index
```

---

<a name="bug-7"></a>
## Bug 7 — an impossible chunk-size config produced nothing, silently

**Severity: low.**

### Symptom

`min_words` greater than `target_words` means no chunk can ever qualify, so the chunker
returned `[]` — indistinguishable from "this article had no usable text". Same for
`overlap_words >= target_words`, where the window cannot advance.

### Reproduce it

```bash
./.venv/bin/python - <<'EOF'
from rag.corpus.chunk import chunk_article
for kw in ({"target_words": 50, "min_words": 200},
           {"target_words": 100, "overlap_words": 100}):
    try:
        n = len(chunk_article(doc_id="d", title="T", url="u", revision_id=1,
                              text="== S ==
" + " ".join(["w"] * 300), **kw))
        print(f"{kw} -> {n} passages (silent)")
    except ValueError as e:
        print(f"{kw} -> ValueError: {e}")
EOF
```

**Before:** `0 passages` and `401 passages` respectively, both silent. (The 401 came from a
stride of 1 word — 401 near-identical passages, a quality and performance trap.)
**Now:** both raise `ValueError` naming the offending parameters.

### Verify

```bash
./.venv/bin/python -m pytest tests/test_chunk.py -q -k impossible_size
```

---

<a name="bug-8"></a>
## Bug 8 — the labeller crashed on Ctrl-D and lost every judgement

**Severity: high.** The crash was cosmetic; the data loss was not.

### Symptom

`rag.cli label` saved judgements **only after the loop finished.** Any interruption — Ctrl-C,
Ctrl-D, a closed terminal, piped input running out — discarded everything judged so far and
printed a raw traceback over it.

### Reproduce it

```bash
./.venv/bin/python -m rag.cli pool --depth 5      # fresh unjudged pool
printf 'y\nn\ny\n' | ./.venv/bin/python -m rag.cli label
```

**Before:** three answers consumed, then `EOFError: EOF when reading a line` with a
traceback, and `labels.json` unchanged — all three judgements gone.

**Now:**

```
interrupted.

saved 3 judgement(s) to data/eval/labels.json
29 of 32 still unjudged.
Run `label` again to continue where you left off.
```

### Why it mattered most of all eight

Relevance judgements are the one artifact in this component that **cannot be regenerated**.
A corpus can be re-fetched, an index re-embedded in a minute, a bug re-fixed — but a few
hours of human judgement, lost to a closed laptop lid, is simply gone. And the loss was
silent in the worst way: the traceback scrolled past while the real damage was an unchanged
file.

### Two smaller faults found alongside it

- **Invalid input silently skipped a candidate.** Typing `yes` instead of `y` fell through
  every branch, leaving that passage unjudged with no warning. It now re-prompts.
- **`provisional` was cleared unconditionally on exit.** Quitting after 2 of 63 judgements
  marked the whole set hand-judged, so `eval` dropped its warning banner while 61 candidates
  were still unlabelled. It now stays provisional until every candidate is judged.

### Fix

Save after **every** judgement; catch `EOFError` and `KeyboardInterrupt` and report what was
saved; re-prompt on unrecognised input; keep `provisional` set until the pool is complete.

### Verify the fix

```bash
./.venv/bin/python -m rag.cli label < /dev/null        # graceful, no traceback
printf 'maybe\nyes\ny\nq\n' | ./.venv/bin/python -m rag.cli label   # re-prompts twice
```

---

## Not bugs — behaviour that looks wrong but is correct

Worth knowing before someone files these.

**No abstention.** An off-topic claim returns `k` dense results anyway (Chernobyl passages at
0.165 for a claim about Rome). Expected: cosine similarity always has a top-k. It is a real
*gap*, tracked as **D-09**, and it needs the labeled eval set before a threshold can be
defended. Not a coding error.

**Duplicate-looking results.** Two hits from `Paris Agreement / (lead)` are two different
overlapping passages, not one passage twice. Chunks overlap by 35 words by design. Confirm
with `--text`.

**Hybrid scores around 0.03.** RRF sums `1/(60 + rank)`, so ~0.033 is a **first-place**
result. Compare ranks across retrievers, never raw scores.

**Low source diversity in top-k.** For the Paris Agreement claim, 4 of 5 dense hits come from
the same article. Arguably correct — that article *is* the relevant source — but it means a
note would cite essentially one document. Worth revisiting when the note generator lands,
since a "community note" citing a single source is weaker than one citing several.

---

## Demoing this to the team

One command walks through the whole component:

```bash
./.venv/bin/python -m rag.cli demo
```

Six narrated sections: the pinned corpus and its provenance; why embeddings beat word
matching (with measured numbers); Mikko's detector gate accepting 4 of 8 fixture segments;
retrieval across all three retrievers; the abstention gap at 4.1× separation; and the
silent-truncation guard. It ends by stating plainly what is **not** built.

Supporting commands:

```bash
./.venv/bin/python -m rag.cli stats                        # corpus + pinned revisions
./.venv/bin/python -m rag.cli budget                       # encoder safety check
./.venv/bin/python -m rag.cli drift                        # have pinned articles changed?
./.venv/bin/python -m rag.cli claims --text                # fixture claims end-to-end
./.venv/bin/python -m rag.cli search "<claim>" --retriever all --text
./.venv/bin/python -m pytest tests/ -q                     # 20 tests
```

### Three points worth making to the team

1. **Two bugs were invisible from the outside.** Bug 1 and the earlier truncation bug both
   left retrieval *working*, just wrong. That is the argument for `budget` and `drift` being
   commands rather than comments.
2. **Bug 4 would have corrupted a reported number**, not just behaviour — recall@k would have
   read short and looked like a retrieval failure. It is the same "a number needs a control"
   reasoning as D-03, applied to our own plumbing.
3. **Bug 1 invalidated a design decision, not just code.** D-04 originally claimed the corpus
   was regenerable from the manifest. It is not, and the log has been corrected rather than
   quietly patched. Worth saying out loud, because the status report has to describe what
   actually happened.
