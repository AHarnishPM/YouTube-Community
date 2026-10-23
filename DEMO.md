# Demo guide — Retrieval & Grounded Note Generation

A scripted walkthrough: what to type, what appears, what to say. Measured timings so
nothing stalls in front of an audience.

Companions: `TESTING.md` (reference, organised by concept), `BUGS.md` (what broke and why),
`CONCEPTS.md` (the ideas), `DESIGN-LOG.md` (decisions).

---

## Before you present

```bash
cd "CS 4701/YouTube-Community"
./.venv/bin/python -m rag.cli stats
```

If that prints 457 passages and 7 pinned revisions, you are ready. Nothing to install.

**Warm the model cache first.** The first command that touches the encoder loads it from
disk; do this once before anyone is watching:

```bash
./.venv/bin/python -m rag.cli budget
```

**Widen your terminal to ~90 columns.** The tables assume it.

### Timings (measured)

| Command | Time |
|---|---|
| `stats` | 0.2 s |
| `drift` | 3.0 s |
| `demo` | 3.3 s |
| `eval` | 3.2 s |
| `pytest tests/ -q` | 3.4 s |
| `budget` | 5.1 s |

Nothing exceeds about five seconds, so there is no dead air to talk over.

---

## The 5-minute version

One command, six narrated sections:

```bash
./.venv/bin/python -m rag.cli demo
```

Let it print, then walk back through it. What to say at each section:

**1. The evidence corpus.** "Seven Wikipedia articles, fetched once and pinned by revision
ID. Every passage carries title, section, URL and revision — so a citation points at the
*exact* text we read, not at whatever Wikipedia says today."

**2. Why embeddings.** Point at row 1: **cosine 0.747, word overlap 0.133.** "Same meaning,
almost no shared words. 'Photovoltaics' and 'solar', 'lowest-cost' and 'cheapest'. Keyword
search is blind to that; this is why we embed." Then row 3 (0.485): "and it isn't just
counting shared words — nuclear reactors share 'electricity' and 'generate' but score well
below the real paraphrases."

**3. The detector gate.** "Eight transcript segments go in, four come out. The rejects are
an opinion, a story about someone's cousin, and a sponsor read. None of those are
*checkable*, so none deserve a note. That decision is Mikko's component — I consume the
verdict, I don't re-make it."

**4. Retrieval.** "One matrix multiply against 457 passages, a few milliseconds." Then the
trap worth pre-empting: **"The scores aren't comparable across retrievers. Dense is cosine
0–1, BM25 is unbounded, and hybrid uses rank fusion so 0.033 is a *first-place* result.
Compare ranks, never scores."**

**5. No abstention.** "Ask about the Roman Empire and you get Chernobyl passages — at 0.165
instead of 0.673. Expected, not broken: cosine similarity always has a top-k. But it's the
most important open problem, because once note generation exists the model would
confidently cite those. A 4× separation means a threshold will work; I just won't pick it
by eyeballing two examples."

**6. The silent-failure guard.** "The encoder truncates past 256 tokens *silently*. Our
first chunker used 220-word passages, ~290 tokens — the tail of every long passage was
being dropped from the index while retrieval kept appearing to work. This check is why that
can't happen unnoticed."

Close on the last block: **"Note generation isn't built. This ends at retrieved evidence."**
Say it yourself rather than letting someone ask.

---

## The 15-minute version

Add these after `demo`.

### Let them pick a claim

The most convincing thing you can do — hand over the keyboard.

```bash
./.venv/bin/python -m rag.cli search "your claim here" --retriever all -k 3 --text
```

Good ones to suggest, with what to point out:

| Claim | What it shows |
|---|---|
| `"solar is the cheapest way to make electricity"` | **a real ranking miss** — the ideal passage lands at rank 2. See below. |
| `"chernobyl happened in 1986"` | entity-heavy — BM25 is sharp here |
| `"nuclear power has never killed anyone"` | retrieves *Nuclear power / Accidents* — it surfaces context, it does **not** rule on the claim |
| `"the roman empire fell in 476 ad"` | the abstention gap, live |

To show the dense-vs-lexical contrast you need the **full** fixture phrasing, not a short
query — the effect depends on there being enough words for BM25 to be misled:

```bash
./.venv/bin/python -m rag.cli search "but here's the stat that really got me the international energy agency reported that solar became the cheapest source of new electricity generation in most of the world" --retriever all -k 3
```

There BM25 returns *Nuclear power / Current prospects* — misled by "power"/"energy"
overlap — while dense correctly surfaces *International Energy Agency*. The short query
does **not** reproduce this; BM25 stays on *Solar power*.

### The ranking miss worth showing on purpose

```bash
./.venv/bin/python -m rag.cli search "solar is the cheapest way to make electricity" --retriever dense -k 3 --text
```

```
rank 1  [0.6572]  Solar power / Productivity by location   <- about irradiance and latitude
rank 2  [0.6541]  Solar power / Cost per watt              <- "solar power is the lowest
                                                              cost source of electricity"
```

**The passage that literally answers the claim is ranked second, by 0.003.** All three
retrievers make the same mistake.

This is the best thing in the whole demo to volunteer, because it is precisely the failure
that eyeballing results cannot catch and that nDCG and precision@1 are designed to measure.
What to say: "the right passage is there, but not first, and the margin is three
thousandths. I only noticed because I printed the text. This is exactly why the evaluation
exists — 'the results look relevant' is not a measurement."

**Pre-empt the fairness question.** Someone will suspect cherry-picking. Say: "the corpus is
seven articles on climate and energy, so anything outside that will fail — and that's the
honest limitation. It's also why eyeballing claims can't measure quality; only the eval can."

### Show that reproducibility is real, not claimed

```bash
./.venv/bin/python -m rag.cli drift
```

"Every citation pins a revision ID. This checks them against Wikipedia — the *Paris
Agreement* article has already moved since we fetched it. Our committed corpus still holds
the pinned text, so the numbers stay reproducible. Drift is a notice, not an error." This
lands well because it shows a guarantee being *verified*, not asserted.

### Show the evaluation

```bash
./.venv/bin/python -m rag.cli eval
```

**Read the warning banner out loud.** "These are provisional labels — a smoke test of the
harness, not a result."

Then make the point that matters: "The giveaway is MRR at exactly **1.000** for all three
retrievers. Not because retrieval is perfect — because these labels mark a passage relevant
if it came from the right *article*, so rank 1 always qualifies. That artifact is exactly
why document-level judging is unreportable, and why the real labels are judged per passage."

Showing that you can diagnose your own metric is stronger than showing a good number.

### Show the tests

```bash
./.venv/bin/python -m pytest tests/ -q
```

"48 tests. 14 of them are on the metrics alone, because a wrong metric silently invalidates
every number downstream. One asserts that precision@k divides by k rather than by results
returned — otherwise a retriever returning one hit when asked for five would score 1.0
instead of 0.2."

---

## If the audience is technical: demo a bug

This is the strongest 90 seconds available, because it shows how the work is actually done.

```bash
# from BUGS.md, Bug 1 — still reproduces live, because it is Wikipedia's behaviour
./.venv/bin/python - <<'EOF'
import requests
S = requests.Session(); S.headers.update({"User-Agent": "CS4701-demo (kd497@cornell.edu)"})
API = "https://en.wikipedia.org/w/api.php"
a = S.get(API, params={"action":"query","prop":"extracts","titles":"Paris Agreement",
    "explaintext":"1","format":"json","formatversion":"2"}).json()
plain = a["query"]["pages"][0]["extract"]
rev = S.get(API, params={"action":"query","prop":"revisions","titles":"Paris Agreement",
    "rvprop":"ids","format":"json","formatversion":"2"}).json()
rid = rev["query"]["pages"][0]["revisions"][0]["revid"]
b = S.get(API, params={"action":"query","prop":"revisions","revids":str(rid),
    "rvprop":"ids|content","rvslots":"main","format":"json","formatversion":"2"}).json()
wiki = b["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]
print(f"plaintext extract : {len(plain):>8,} chars | {plain[:60]!r}")
print(f"revision content  : {len(wiki):>8,} chars | {wiki[:60]!r}")
EOF
```

"Our `--pinned` rebuild was supposed to re-fetch exact revisions. It returned 119,907
characters of wiki markup where the normal path gives 38,142 of clean prose — and the
obvious fix, asking for a plaintext extract *at* a revision, silently returns today's text
with no warning. There is no plaintext-at-revision endpoint. So the design assumption was
false, not the code. We now commit the corpus text, and the manifest's job narrowed to
detecting drift."

The point to land: **"two of our bugs left retrieval working, just wrong. That's why
`budget` and `drift` are commands rather than comments."**

---

## Walking through the labelling workflow

Only show this if someone asks how the evaluation gets its ground truth.

```bash
./.venv/bin/python -m rag.cli pool --depth 10     # build the worksheet
./.venv/bin/python -m rag.cli label               # judge, y/n/s/q
./.venv/bin/python -m rag.cli eval                # score
```

⚠️ **`pool` overwrites `data/eval/labels.json`.** Back it up first if you want the demo-ready
provisional labels afterwards:

```bash
cp data/eval/labels.json /tmp/labels.bak.json     # restore with cp back
```

What to say: "Judging all 457 passages against 50 claims is 22,850 decisions. Pooling — the
standard method since TREC in 1992 — takes the union of all three retrievers' top-10 and
judges only that: about 16 per claim. The cost is explicit: a relevant passage no retriever
surfaced never gets judged, so pooled recall is an *upper bound* on true recall. `eval`
prints the unjudged fraction so you can see when the pool was too shallow."

`label` saves after every answer, so it is safe to stop mid-session and resume.

---

## Questions you will get

**"So does it fact-check videos?"**
No — and that's deliberate. It adds cited context and withholds any verdict on whether the
speaker is right. A wrong verdict is far worse than an unhelpful note, verification is much
harder NLP, and summarising supplied passages is *checkable* in a way that a verdict isn't.
(`CONCEPTS.md` §1.)

**"How good is the retrieval?"**
Unknown, honestly. The harness is built and tested; the labels aren't done, so there's no
defensible number yet. Anything I said now would be an impression, not a measurement.

**"Why not just use the ChatGPT/Claude API?"**
Cost and reproducibility. Batch-processing hundreds of hour-long transcripts makes per-token
pricing dominate the budget, and a pinned local model means results don't drift when a
provider updates silently. Everything runs on Llama 3.2 through Ollama, locally.

**"Why Wikipedia and not web search?"**
Web search isn't reproducible — it would destroy the pinned-corpus argument. The tradeoff is
coverage: Wikipedia is thin on recent events and niche claims, which is a stated limitation
rather than a hidden one. (D-04.)

**"Only 7 articles?"**
Yes — it's a working corpus, sized to develop against, not the final one. Scaling is a
`--titles-file` away; the index rebuild takes about a minute.

**"Isn't BM25 redundant if dense is better?"**
That's the question the eval answers rather than assumes. Without a baseline, "recall@5 =
0.62" is uninterpretable — good or bad depends entirely on what keyword search gets. (D-03.)

---

## Do not oversell these

Say them before someone finds them:

- **Note generation does not exist.** Strictly, this is the **R**, not the RAG.
- **No measured retrieval quality.** Harness yes, labels no, number no.
- **No abstention.** Off-topic claims still return results (D-09).
- **The corpus is 7 articles.** Hand-picked to cover the fixture claims.
- **Transcripts and claim detections are fixtures**, not real data — deliberate, so this
  component could be built without waiting on teammates (D-02).
- **Firebase changed the plan.** The team's database is Firebase, not PostgreSQL, so the
  pgvector migration path is gone and needs a new decision.
- **Aaron's transcripts have no `segment_id`**, which is the whole interface with Mikko's
  detector — a real blocker for integration regardless of this component.

Stating limits yourself reads as competence. Having them discovered reads as the opposite.
