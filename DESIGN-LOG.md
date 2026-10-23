# Design Log — Retrieval & Grounded Note Generation (Member 3)

**Owner:** Kenza Daoudi (kd497) · **Branch:** `kenza/rag-core`
**Started:** 2026-10-22

## What this file is

A running engineering record of the RAG component: **what** we are building, **how** we
are building it, **why**, and — most importantly — **every place we depart from the
submitted project proposal**.

Two reasons it exists:

1. Milestone 3 and Milestone 5a both require us to explain how the project changed since
   the proposal. This file is the raw material for that explanation.
2. Milestone 5c (individual report) asks for each member's own contributions. This is the
   record of mine.

> **Note on scope:** this is a working engineering document — technical decisions and
> their rationale. It is *not* report prose. Per the course AI policy, the proposal,
> status report, and final report must be written by a human, so the writing in those
> documents has to be yours even where it draws on facts recorded here.

## Reference: what the proposal committed to

From the submitted proposal (`CS4701 AI Prac.pdf`), *AI-Powered Community Notes for
YouTube*, my lane is **Retrieval and Grounded Note Generation** — "the RAG core, which is
the heart of the 'Community Notes' idea."

| Weeks | Committed deliverable |
|---|---|
| 1–2 | Choose and build the external evidence corpus; embeddings (`sentence-transformers`) with PostgreSQL vector search |
| 3–4 | Retrieval pipeline + retrieval evaluation (does relevant evidence appear in top-k for a labeled claim subset?) |
| 5 | Note generator: claim + retrieved passages → concise, source-cited note that does **not** declare the speaker right or wrong. Wire up claim detection → retrieval → note with Member 2's detector |
| 5–9 | RAG notes vs. LLM-only notes; rating rubric for outside evaluators (accuracy to video, support from cited evidence, usefulness); final ablations |

**Metrics I own:** retrieval top-k quality, and the RAG vs. no-RAG grounding /
hallucination study.

Proposal stack for this component: Ollama + Llama 3.2, `sentence-transformers`, "FAISS or
PostgreSQL/pgvector", FastAPI, PostgreSQL, Docker Compose.

---

## Divergences from the proposal

Each entry: what the proposal said, what we are doing instead, and why. Status is
`DECIDED`, `PROPOSED` (awaiting Kenza's sign-off), or `OPEN`.

### D-01 · Timeline has slipped — weeks 1–5 of my lane are not done · `DECIDED`

**Proposal:** evidence corpus, embedding index, retrieval pipeline, retrieval eval, and
the note generator all complete by week 5.

**Reality as of 2026-10-22:** none of it is built. The shared repo holds three commits —
a two-line README on `main` and a Hello-World browser extension on `chrome-extension`.
Transcript ingestion and the Postgres schema (Member 1) and the claim detector (Member 2)
are likewise not in the repo.

**Why it matters:** this is the single largest divergence and the status report has to
state it plainly. It also resets the dependency math — see D-02.

**Consequence:** the remaining work is re-sequenced to put a measurable result first
rather than building the component in proposal order. See *Build plan* below.

### D-02 · Decouple from Member 1's Postgres: local vector store first, pgvector later · `PROPOSED`

**Proposal:** "set up embeddings (`sentence-transformers`) with PostgreSQL vector search."
The proposal's software list already allows "FAISS **or** PostgreSQL/pgvector."

**Instead:** build against a local index (FAISS, or brute-force NumPy while the corpus is
small) behind a narrow `VectorStore` interface. Swap in pgvector once Member 1's database
exists, as a config change rather than a rewrite.

**Why:** the proposal's own dependency analysis names Member 1 as "the bottleneck early,"
and that bottleneck has now materialised. My component does not actually need their
schema: retrieval maps claim text → evidence passages, and the evidence corpus is mine.
Waiting on Postgres would block the one deliverable nobody else can produce.

**Cost:** one adapter to write, and a later migration to verify. Cheap relative to idling.

### D-03 · Add a lexical (BM25) retrieval baseline · `PROPOSED`

**Proposal:** promises retrieval evaluation, but only against dense embedding retrieval —
no retrieval baseline. (A baseline was promised for *claim detection*, which is Member 2's.)

**Instead:** also implement BM25 and report dense vs. BM25 vs. hybrid on the same labeled
claim subset.

**Why:** three reasons. It makes "is retrieval working?" answerable rather than assumed —
recall@k of 0.6 means little until you know a keyword search gets 0.5 or 0.3. The
guidelines weight evaluation at 30% and warn against "sloppy or hand-wavy discussions of
performance." And it is cheap: BM25 over an already-chunked corpus is a small amount of
code, with no model to train.

**This is an addition, not a substitution** — the committed dense-retrieval eval still happens.

### D-04 · Evidence corpus: pinned Wikipedia subset · `DECIDED` (2026-10-22)

**Proposal:** "a fixed corpus of publicly available reference material that can be indexed
for evidence retrieval, allowing our RAG experiments to remain reproducible." No specific
source named.

**Why it needs deciding now:** it is the week-1 item everything else sits on, and the
guidelines are explicit that you should discuss "the data that you've already found," not
data you intend to look for.

Options under consideration:

| Option | For | Against |
|---|---|---|
| Wikipedia snapshot (pinned dump or HF `wikimedia/wikipedia`) | Broad coverage, genuinely fixed, trivially citable, well-trodden for RAG | Thin on recent events and niche podcast claims |
| Wikipedia + a small hand-curated set of source documents per video | Closes coverage gaps on the specific claims we evaluate | Curation effort; risks looking like we tuned the corpus to the claims |
| Live web search | Best coverage | Not reproducible — kills the pinned-corpus argument the proposal makes |

**Decided:** pinned Wikipedia subset, with evaluation videos chosen so their claims are
plausibly Wikipedia-coverable. The coverage limit gets documented as a stated constraint
rather than hidden.

**How the pin works** (`rag/corpus/wikipedia.py`): Wikipedia article text changes daily, so
a citation naming only a title does not identify the evidence we actually retrieved. Each
fetch records the article's **revision ID**, and that is what a `Source` carries.

> ### ⚠️ Corrected 2026-10-23 — the original mechanism did not work
>
> This entry first specified: commit a small manifest of revision IDs, gitignore the bulky
> article text, and regenerate the corpus by re-fetching those revisions. **That is
> impossible.** Wikipedia's plaintext extract (`explaintext`) is served only for an
> article's *current* revision. Asking for a historical revision's content returns raw
> wikitext instead — 119,907 characters of `{{templates}}` and `[[links]]` where the
> extract gave 38,142 of clean prose — and asking `extracts` for a revision id **silently
> returns today's text with no warning**.
>
> So a `--pinned` rebuild would have indexed markup while reporting success. Full repro in
> `BUGS.md` (Bug 1).
>
> **What changed:** the corpus text is now the reproducible artifact and is **committed**
> (324K). `build --pinned` reuses it rather than re-fetching. The manifest's job narrowed
> from *regenerate* to *detect drift*, via `check_drift()` and the `drift` command. The
> `revision_id` parameter was removed from `fetch_article` entirely — a parameter that
> silently returns a different content format is worse than no parameter.

Current arrangement:

- **committed:** `data/corpus/articles.jsonl` — the pinned article text. The only thing that preserves what we actually read.
- **committed:** `data/corpus/manifest.json` — titles + revision IDs. Used to *detect* drift, not to undo it.
- **gitignored:** `data/index/` — embeddings, regenerable from the corpus in ~1 minute.

`rag.cli drift` reports which articles have moved since the corpus was built. We cannot
recover the old text from Wikipedia, but a stale index is now a reported fact rather than a
silent one.

**Open question for the team:** choosing evaluation videos partly for evidence coverage is a
defensible experimental decision, but it must be disclosed in the report.

### D-05 · Grounding measured programmatically, not only by human raters · `PROPOSED`

**Proposal:** outside evaluators rate notes on accuracy to the video, support from cited
evidence, and usefulness.

**Instead:** keep the human study *and* add an automatic per-sentence grounding check —
for each sentence of a generated note, is it entailed by at least one cited passage?

**Why:** the human study is ~5 participants and runs late in the semester. It cannot give
the fast feedback loop needed to iterate on prompts, and it produces too few samples to
separate RAG from LLM-only with any confidence. An automatic check runs over hundreds of
notes in minutes, and the human ratings then validate the automatic metric on a subset.

**Addition, not substitution** — the rubric and evaluator study still happen.

### D-06 · Embedding model and chunk size pinned to a measured token budget · `DECIDED` (2026-10-22)

**Proposal:** "`sentence-transformers` to generate embeddings." No model or chunk size named.

**Decided:** `all-MiniLM-L6-v2` (384-dim, CPU-fast, the standard sentence-similarity
baseline), with passages of **150 words / 35 overlap**.

**Why those numbers, and why they are not arbitrary:** the encoder truncates input at 256
word-pieces *silently*. Our first chunker used 220-word passages, which measure at ~290
tokens — the tail of every long passage would have been dropped from the index while
retrieval continued to appear to work. Measured with `rag.embed.check_chunk_budget()`:

| target words | measured tokens | model limit | headroom |
|---|---|---|---|
| 150 | 190 | 256 | 66 |

This is the kind of bug that shows up only as "retrieval is mysteriously mediocre," so the
budget check is a function we can re-run rather than a comment. A related bug is now locked
down by a regression test: the MediaWiki plaintext extract puts each paragraph on one line,
so paragraph-at-a-time chunking could not bound passage size at all — a 600-word paragraph
passed through whole. Chunking now windows *within* a section.

### D-07 · Exact brute-force search instead of FAISS · `DECIDED` (2026-10-22)

**Proposal:** "FAISS or PostgreSQL/pgvector."

**Decided:** neither, for now — an exact dot product over an in-memory NumPy matrix, behind
the `VectorStore` interface from D-02.

**Why:** at our scale (7 articles already give 458 passages; a few hundred articles give
order 10k) an exact search over a 10k×384 matrix takes milliseconds. FAISS would add a
dependency and an *approximation* to buy speed we do not need. That approximation matters
here specifically because the quantity under measurement **is** retrieval quality: with an
exact index, a disappointing recall@k is the retriever's fault and not the index's. Swap in
FAISS or pgvector if the corpus grows enough to need it.

### D-08 · Hybrid retrieval by reciprocal rank fusion · `DECIDED` (2026-10-22)

Follows from D-03: having built dense and BM25, combining them is nearly free. RRF fuses
**ranks** rather than scores, which avoids normalising cosine similarity against BM25's
unbounded scale — no weighting hyperparameter to tune, so no risk that the fusion's apparent
advantage is really a tuned constant. `rrf_k = 60`, the value from the original paper.

**Second observation, 2026-10-23 — a ranking miss found by hand.** On the claim "solar is
the cheapest way to make electricity", dense returns *Solar power / Productivity by
location* (irradiance, latitude, temperature) at rank 1 with 0.6572, and *Solar power /
Cost per watt* — which contains "solar power is the lowest cost source of electricity" —
at rank 2 with 0.6541. **A margin of 0.003 separates the right answer from a wrong one,**
and all three retrievers order them the same way.

Two things follow. First, top-1 accuracy is weaker than the headline scores suggest, and
score magnitude says little about ordering quality at these margins. Second, this is
exactly the failure mode hand-testing cannot catch: the result set *looks* entirely
plausible — three Solar power passages at ~0.65 — and only reading the text reveals the
ordering is wrong. It is the concrete argument for nDCG and precision@1 alongside recall@k
(D-10), and for not trusting an impression in place of a measurement.

**Early observation, not yet a result:** on the fixture claims, BM25 retrieved
*Nuclear power / Current prospects* for a claim about the IEA and solar costs — misled by
"power"/"energy" overlap — where dense retrieval correctly surfaced the IEA article. That is
the dense-vs-lexical contrast D-03 was added to quantify. It needs the labeled eval set
(step 3) before it counts as evidence.

### D-09 · Retrieval has no abstention; a threshold must be learned, not guessed · `OPEN`

**Proposal:** silent on this. It describes retrieving evidence and generating a grounded
note, but never addresses the case where the corpus holds no relevant evidence at all.

**The behaviour today:** retrieval always returns `k` passages, because cosine similarity
always has a top-k. Asked about a claim the corpus cannot support, it returns the
least-distant irrelevant passages:

| Claim | Corpus coverage | Top dense score |
|---|---|---|
| "the paris agreement was adopted in 2015" | covered | **0.657** |
| "the roman empire fell in 476 ad" | absent | **0.166** (returns Chernobyl passages) |

**Why it matters more than it looks:** this is the difference between a note that adds
context and a note that staples Chernobyl passages to a claim about Rome. The proposal's
own framing — "a note that confidently misdescribes what a creator said is worse than no
note" — makes abstention a correctness requirement, not a nicety. D-05's grounding check
catches an ungrounded note after the fact; abstention prevents generating it.

**The separation is a factor of four, so a threshold is clearly viable.** But the cutoff
must be chosen on the labeled eval set from step 3, not by eyeballing two examples. A
threshold tuned on examples we picked is a number we cannot defend in the report.

**Deferred until step 4** — it needs the same labeled data, and choosing it earlier means
choosing it badly. Documented for users in `TESTING.md`.

### D-10 · Retrieval eval uses pooled, passage-level relevance judgements · `DECIDED` (2026-10-23)

**Proposal:** "For a subset of claims, we will identify relevant evidence and measure
whether our retrieval system surfaces it within its top results." It does not say at what
granularity, or how the judging is made tractable.

**Decided:** **pooled passage-level** judging, the standard TREC method.

**Why pooling.** Judging all 457 passages against each of ~50 claims is 22,850 decisions.
Instead, run every retriever, take the union of their top-N, and judge only that pool —
about 16 passages per claim at depth 10. Hours of work, not weeks.

The pool is drawn from **all three** retrievers, not just the one under test. Pooling only
dense results would penalise BM25 for finding relevant passages that were never judged,
which would quietly rig the D-03 comparison.

**The cost, stated plainly:** a relevant passage no retriever surfaced is never judged, and
unjudged passages count as not relevant. So **pooled recall is an upper bound on true
recall.** This is a known, citable limitation of the method and must appear in the report
rather than be discovered by a reader. `eval` prints the unjudged fraction of returned
results for exactly this reason: if it is high, the pool was too shallow to judge what is
being returned.

**Why not document-level judging** (counting a passage relevant because it came from the
right article): far too coarse. It ignores whether the passage bears on the claim at all,
and with only 7 articles a retriever could score well by topic alone. Measured on the
provisional title-based labels, MRR came out at exactly 1.000 for all three retrievers —
not because retrieval is perfect but because rank 1 always came from the right article.
That is the artifact that makes document-level judging unreportable.

**Keyed by content hash, not passage id.** `passage_id` embeds a chunk index, which shifts
whenever chunking changes — fixing the bibliography leak (BUGS.md Bug 2) renumbered every
chunk after it. Labels keyed on those ids would have silently pointed at the wrong
passages. Keys are now `sha1(normalised text)[:12]`, and `eval` reports stale keys when the
pool no longer matches the corpus.

**Metrics.** recall@k is the committed one. precision@k, MRR and nDCG@k come nearly free
once labels exist and answer different questions (noise, reader effort, rank quality).
Metrics live in `rag/eval/metrics.py` with 14 dedicated tests, because a wrong metric
silently invalidates every number downstream.

---

## What we're building, and how it fits

The project's claim is that a viewer watching a long video lacks context at the moment
they need it. Three components deliver that, and mine is the middle one:

```
Member 1 (Aaron)          Member 2 (Mikko)           Member 3 (Kenza)         Member 1
──────────────────        ─────────────────          ────────────────         ────────
YouTube URL               transcript segments        context-worthy claim     Note object
  → transcript        →     → which segments     →     → retrieve evidence  →   → API
  → Postgres                  need context             → generate cited note    → extension
                            (+ chapters)
```

Member 2 decides *where* a note is needed. I decide *what the note says* — and the project's
central safety argument lives here: the note must summarise evidence and cite it, never
adjudicate the speaker as right or wrong. A note that confidently misdescribes what a
creator said is worse than no note at all, so "grounded" is the requirement, not a feature.

### Components

**1. Evidence corpus + chunker.** Pinned public reference text, split into passages of a
few hundred tokens with overlap. Every chunk keeps provenance — source title, URL, chunk
index — because a note that cannot cite is a note we cannot ship.

**2. Embedding index.** `sentence-transformers` (starting with `all-MiniLM-L6-v2`: 384-dim,
fast on CPU, a standard baseline), pinned by version so results don't drift. Behind a
`VectorStore` interface — see D-02.

**3. Retrieval.** `retrieve(claim_text, k) -> [EvidencePassage]`, with dense, BM25, and
hybrid variants so the ablation is a flag rather than a branch.

**4. Retrieval eval.** A labeled subset: for each claim, which source documents count as
relevant. Reports **recall@k** (the proposal's committed metric) plus MRR and nDCG.

**5. Note generator.** Llama 3.2 via Ollama, prompted with the claim and the top-k
passages, emitting structured JSON so citations are machine-checkable rather than parsed
out of prose. Hard constraints in the prompt *and* verified after generation: cite only
supplied passages, do not declare the speaker right or wrong, stay concise.

**6. Grounding / hallucination study.** Same claims, two conditions — with retrieval and
without. Automatic per-sentence support check (D-05) over the full set, human ratings on a
subset.

**7. FastAPI endpoint.** Exposes the pipeline so Aaron's backend can call it, emitting the
agreed Note object.

### Interface contracts

Locked in the proposal; treat as fixed unless renegotiated with the team.

```
TranscriptSegment  video_id, start, end, text            # Member 1 → Postgres
ClaimDetection     segment_id, is_context_worthy, confidence   # Member 2 → me
Note               video_id, timestamp, claim_text, note_text, sources[]  # me → API → extension
Chapter            video_id, start, title                # Member 2 → API → extension
```

I will define these as typed models on this branch so the boundary is executable, and
hand-write fixtures for `TranscriptSegment` and `ClaimDetection` so I can build and
measure before either teammate lands their side.

---

## Build plan

Ordered to produce a defensible number as early as possible, not to follow proposal order.

| # | Step | Produces | Needs |
|---|---|---|---|
| 0 | Python project skeleton, pinned deps, typed interface models, hand-written fixtures | A runnable package, no external blockers | — |
| 1 | Pick + ingest evidence corpus; chunk with provenance | Indexed passage store | D-04 resolved |
| 2 | Embedding index + `VectorStore`; dense `retrieve()` | Working retrieval | 1 |
| 3 | Hand-label ~40–60 claims with relevant source docs | Retrieval eval set | 1 |
| 4 | **Retrieval eval: recall@k, dense vs. BM25** | **First real result** | 2, 3 |
| 5 | Note generator + structured citations against Llama 3.2 | End-to-end claim → note | 2 |
| 6 | Automatic grounding check; RAG vs. LLM-only run | Hallucination numbers | 5 |
| 7 | Rating rubric + evaluator instructions | Human study ready | 6 |
| 8 | FastAPI endpoint; swap to pgvector | Integration with Aaron | Member 1's DB |
| 9 | Integrate Member 2's real detector (replaces fixtures) | True end-to-end | Member 2 |

Step 4 is the milestone that matters: it is the first point at which my component has a
measured result rather than an intention.

## Risks

- **Llama 3.2 is 3B.** Small models follow citation and abstention constraints poorly. If
  it will not reliably refuse to adjudicate, mitigations in order: tighter structured
  output, few-shot examples, then a larger local model if the hardware allows. A finding
  that a 3B model *cannot* be held to grounding constraints is itself a reportable result.
- **Corpus coverage** (D-04). If Wikipedia does not cover the claims in our videos,
  retrieval recall will be floor-level for reasons that have nothing to do with the
  retriever. Measure coverage *before* investing in retrieval tuning.
- **Labeling effort.** Steps 3 and 7 are hand work and cannot be compressed much.
- **Integration slip.** Steps 8–9 depend on teammates. Everything through step 7 is
  deliberately independent of them.

## Status

| Date | Entry |
|---|---|
| 2026-10-22 | Branch `kenza/rag-core` created off `main`. Design log opened, build plan drafted. |
| 2026-10-22 | **Steps 0–2 done.** Interface contracts as typed models (`rag/models.py`); hand-written upstream fixtures; Wikipedia fetcher with revision pinning; section-aware chunker; embedding layer with token-budget check; exact vector store with persistence; dense + BM25 + hybrid retrievers. 11 tests passing. |
| 2026-10-22 | End-to-end smoke test: 7 articles → 458 passages → all three retrievers return plausibly relevant evidence for all four fixture claims. Index persisted to `data/index/`. **Not a result** — no labeled eval set yet. |
| 2026-10-23 | **Bug hunt: 5 bugs found and fixed**, documented with repro steps in `BUGS.md`. One (Bug 1) invalidated the D-04 pinning mechanism, now corrected above. Tests 11 → 20. Corpus 458 → 457 passages (Bug 2 was indexing a leaked bibliography section). Added `drift` and `demo` commands. |
| 2026-10-23 | `CONCEPTS.md` written — concepts, measured numbers, and clarifications C-1…C-8. |
| 2026-10-23 | **Step 4 harness built** (not yet a result): `rag/eval/` with pooled passage-level labelling, recall@k / precision@k / MRR / nDCG@k, and `pool` / `label` / `eval` commands. Methodology logged as D-10. Two more bugs found and fixed (BUGS.md 6–7). Tests 20 → 48. |
| 2026-10-23 | Audited teammates' work: Aaron pushed transcript ingestion today — **Firebase, not PostgreSQL**, which invalidates the D-02 pgvector target. Nothing from Member 2 in the repo. See the answer in the status notes. |

### Done

- [x] **0** — project skeleton, pinned deps, typed contracts, fixtures
- [x] **1** — evidence corpus: fetch, revision-pin, chunk with provenance
- [x] **2** — embedding index, `VectorStore` boundary, dense/BM25/hybrid retrieval

### Next

- [ ] **3** — hand-judge the pooled candidates (`rag.cli label`) ← *blocking, and only you can do it*
- [x] **4a** — eval harness: pooled labelling, 4 metrics, 3 retrievers, tested
- [ ] **4b** — run it on real labels ← **first real result**
- [ ] **5** — note generator with structured citations against Llama 3.2
- [ ] **6** — automatic grounding check; RAG vs LLM-only
- [ ] **7** — rating rubric for outside evaluators
- [ ] **8** — FastAPI endpoint; pgvector swap *(needs Member 1)*
- [ ] **9** — real detector in place of fixtures *(needs Member 2)*

Step 3 is hand work and cannot be automated away: deciding which passages count as
relevant evidence for a claim is the judgement the whole evaluation rests on. It is also
the gate on step 4, which is the first number worth reporting.

## Environment notes

- `ollama` installed, `llama3.2:latest` pulled (2.0 GB, as of 5 weeks ago).
- `docker` and `docker-compose` available; no local `psql` client (the container provides one).
- Repo cloned over HTTPS. **Push access is not configured** — the SSH key in `~/.ssh` is
  not authorized for github.com, so pushing this branch needs auth set up first.
- `~/YouTube-Community/PROPOSAL.md` is an unrelated earlier draft ("Beyond the Timeline",
  two members). It is **not** the submitted proposal; the submitted text is in
  `CS4701 AI Prac.pdf`. Do not quote the former in the status report.
