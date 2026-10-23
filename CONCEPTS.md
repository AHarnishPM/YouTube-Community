# Concepts — Retrieval & Grounded Note Generation (Member 3)

Reference notes for the component Kenza owns: the ideas it rests on, the terminology,
and the measurements taken on our own system rather than quoted from a textbook.

Companion documents: `DESIGN-LOG.md` (decisions and divergences from the proposal),
`TESTING.md` (how to drive the pipeline by hand).

**Last updated:** 2026-10-23

---

## Contents

1. [What the system is actually for](#1-what-the-system-is-actually-for)
2. [Terminology: one piece of text, four names](#2-terminology-one-piece-of-text-four-names)
3. [Stage 1 — the detector (Mikko's)](#3-stage-1--the-detector-mikkos)
4. [Measuring a classifier: precision, recall, F1](#4-measuring-a-classifier-precision-recall-f1)
5. [Why a baseline is non-negotiable](#5-why-a-baseline-is-non-negotiable)
6. [The `ClaimDetection` contract](#6-the-claimdetection-contract)
7. [Embeddings](#7-embeddings)
8. [Indexing (and how it differs from caching)](#8-indexing-and-how-it-differs-from-caching)
9. [Chunking](#9-chunking)
10. [Why citation precision depends on chunking](#10-why-citation-precision-depends-on-chunking)
11. [Retrieval is arithmetic](#11-retrieval-is-arithmetic)
12. [The generator](#12-the-generator)
13. [What RAG actually buys us](#13-what-rag-actually-buys-us)
14. [Abstention: the open hole](#14-abstention-the-open-hole)
15. [The two answer keys — neither exists yet](#15-the-two-answer-keys--neither-exists-yet)
16. [Clarifications and corrections on the record](#16-clarifications-and-corrections-on-the-record)
17. [Measured numbers in one place](#17-measured-numbers-in-one-place)
18. [Glossary](#18-glossary)

---

## 1. What the system is actually for

**It adds context. It does not deliver verdicts.** This is the single most important thing
to keep straight, because it defines what counts as success.

From the proposal:

> "Importantly, we do not want the LLM itself to simply declare that someone in a video is
> 'right' or 'wrong.' Instead, its role is to find and summarize useful evidence while
> keeping the generated note traceable to its sources."

And from the plan of action, describing this component's week-5 deliverable: a note
generator producing *"a concise, source-cited note that doesn't declare the speaker right
or wrong."*

| | Fact-checking — **not this** | Contextualization — **this** |
|---|---|---|
| Output | "FALSE — the target was 1.5 °C" | "The agreement's goal is holding warming well below 2 °C, while pursuing 1.5 °C. [1]" |
| Requires | stance detection + a judgement that evidence is *sufficient* | retrieve, summarize, cite |
| Worst failure | a confident, wrong, possibly defamatory verdict | an unhelpful or irrelevant note |

The confusing part: claims are selected **for being verifiable**, but the note deliberately
withholds the verification. That is intentional, for three reasons:

1. **The failure mode is gentler** — a bad note is useless rather than libellous.
2. **Verification is much harder NLP.** Deciding whether evidence *contradicts* a claim, and
   whether you hold enough of it to say so, is beyond a 3B local model.
3. **Summarizing supplied passages is checkable.** The evidence is right there to compare
   against — which is the entire basis of the grounding study (D-05).

**Consequence for evaluation:** the metric is *"is this note supported by its citations, and
is it useful?"* — never *"is the verdict correct?"* There is no verdict.

---

## 2. Terminology: one piece of text, four names

The same material gets renamed at each stage. Most early confusion traces to this.

| Stage | Name | Concretely |
|---|---|---|
| On Wikipedia's servers | — | the *Paris Agreement* article |
| After fetching | **reference text** / **article** | 38,148 chars in `data/corpus/articles.jsonl` |
| After chunking | **passage** | 53 pieces of ~150 words |
| Cited in a note | **source** | `Paris Agreement / Effectiveness` + revision ID |

"Reference material", "evidence corpus", "sources" and "passages" all name the same thing at
different points in the pipeline. Our corpus today: **7 articles → 458 passages**, 324K on disk.

A **passage is not live web data.** It was downloaded once, in advance. At query time nothing
touches the network.

### Two different splitting operations

Both sides of the project split text, which invites confusion:

| | Transcript segments | Evidence passages |
|---|---|---|
| Source | YouTube captions | Wikipedia articles |
| Split by | caption timings (arrives pre-split) | our chunker |
| Owner | Aaron (Member 1) | **us** |
| Role | where claims are found | where evidence is found |

**We chunk articles, never transcripts.**

---

## 3. Stage 1 — the detector (Mikko's)

### What "the detector" is

Not a downloadable tool or a named model. It is **a classifier Mikko writes** — a function
from text to a label:

```
in:   "honestly i've always felt like these agreements are mostly symbolic"
out:  not context-worthy
```

He builds **two** versions and compares them:

- **Rule/keyword baseline** — hand-written regexes. Looks for first-person stance markers,
  personal referents, ad-read phrasing, dates, statistics. Crude, instant, free, fully
  transparent.
- **LLM classifier** — Llama 3.2 prompted per segment, returning JSON. Slower, opaque,
  but handles phrasings nobody wrote a rule for.

### The actual test: checkability, not truth

The question is **not** "is this true?" It is:

> Could someone outside this video, using public sources, *in principle* determine whether
> this is accurate?

You don't need to know an answer to know that a question *has* one.

| Fixture segment | Checkable? | Why |
|---|---|---|
| "the paris agreement was adopted in 2015... two degrees celsius" | ✅ | treaty, year, number — public record settles it |
| "carbon dioxide passed four hundred parts per million" | ✅ | a measurement; published datasets settle it |
| "i've always felt these agreements are mostly symbolic" | ❌ | a *feeling* — no source speaks to it |
| "my cousin works in solar and says the industry is booming" | ❌ | **private referent** — no public source knows the cousin |
| "use code podcast for twenty percent off" | ❌ | an instruction, not an assertion about the world |

### Signals per category

- **Factual claim** → points at something external and public: number, date, named entity, event, study.
- **Opinion** → first-person stance markers ("I think", "honestly", "I've always felt"), evaluative adjectives. The sentence is about the speaker's mind, not the world.
- **Anecdote** → a *private* referent. **The subtle case:** "my cousin works in solar" is structurally a factual assertion; it is simply not checkable, because nobody outside can access the subject.
- **Ad read** → second-person imperatives ("use code", "go to"), discount codes, URLs, brand names, register shift.

### The second filter: checkable ≠ worth a note

> "the model will determine whether a claim is **specific enough** that retrieving outside
> information could meaningfully help a viewer understand it."

"Water boils at 100 °C" is checkable and a worthless note. The real gate is **two** tests:
checkable **and** a viewer gains something.

### This boundary is genuinely fuzzy

"The Paris Agreement was basically useless" mixes a checkable referent with an evaluative
claim. That fuzziness is exactly why Mikko's week-1 task is *writing annotation guidelines* —
without them two human labelers disagree and the ground truth becomes noise.

---

## 4. Measuring a classifier: precision, recall, F1

First you need **ground truth**: humans label N segments by hand against the guidelines.
That is the answer key. Then run the detector over the same N and compare. Every segment
lands in one of four buckets:

|  | detector says **yes** | detector says **no** |
|---|---|---|
| **actually yes** | True Positive ✅ | False Negative ❌ *(missed a claim)* |
| **actually no** | False Positive ❌ *(flagged an opinion)* | True Negative ✅ |

**Precision** — of everything flagged, how much was right?

```
precision = TP / (TP + FP)
```
*"When it speaks up, can I trust it?"* Low precision → notes stapled to opinions and ad reads.

**Recall** — of everything it should have caught, how much did it catch?

```
recall = TP / (TP + FN)
```
*"How much slips past?"* Low recall → claims with no note.

**F1** — the harmonic mean:

```
F1 = 2 × (precision × recall) / (precision + recall)
```

### Why both, always

Either alone is trivially gamed:

- Flag **everything** → recall 1.00, precision terrible.
- Flag **only the single most blatant claim** → precision 1.00, recall ~0.

F1 stays low unless both are decent, which is why it resists that gaming.

---

## 5. Why a baseline is non-negotiable

Say the LLM detector scores **F1 = 0.74**. Is that good?

**Unanswerable in isolation.** It only means something beside a comparison:

| Baseline scores | LLM gain | Conclusion |
|---|---|---|
| 0.71 | +0.03 | All that compute for nothing. Ship the regexes. |
| 0.45 | +0.29 | The LLM is doing real work. Justified. |

Same 0.74, opposite conclusions. **The baseline is the control** — it converts a number into
a finding.

This is identical to the reasoning behind **D-03** in our own lane. The proposal promised a
retrieval evaluation but no retrieval *baseline*, so "recall@5 = 0.62" would have been just
as uninterpretable. Adding BM25 fixes it. The course guidelines weight evaluation at 30% and
warn specifically against *"sloppy or hand-wavy discussions of performance."*

---

## 6. The `ClaimDetection` contract

```python
ClaimDetection(segment_id="fx001-1", is_context_worthy=True, confidence=0.95)
```

A small data record passed from Mikko's code into ours. Three fields:

**`segment_id="fx001-1"`** — *which* segment, by ID. Note it carries **no text**: the text
lives in Aaron's database, and a second copy could drift out of sync. The ID is a pointer to
look up. (`fx001` = fixture video 1; `-1` = its second segment.)

**`is_context_worthy=True`** — the verdict, and **our gate**. We retrieve for `True` records
and ignore `False` ones. We do not re-litigate the judgement; if an opinion reaches
retrieval, the bug is in the detector.

**`confidence=0.95`** — certainty, 0–1. Kept separate from the verdict so *we* can make
decisions later without rerunning Mikko's model: process high-confidence claims first, or
drop everything below 0.8 if low-confidence claims turn out to produce bad notes. The
verdict is a switch; confidence is a dial.

**Why it is a "contract":** the three of us fixed these field names in week 1. As long as
Mikko emits this shape, he can rewrite his detector freely and our code never changes. That
is precisely what lets us build today against hand-written fixtures of this shape and swap in
his real detector later with no rewrite (**D-02**).

---

## 7. Embeddings

### The problem

We have a claim and 458 passages. Which passages are relevant?

The obvious approach — **match words** — fails immediately:

```
claim:    "solar became the cheapest source of new electricity generation"
passage:  "photovoltaics now offer the lowest-cost power generation"
```

Identical meaning, **word overlap 0.133**. "Photovoltaics"/"solar" and "lowest-cost"/"cheapest"
are the same idea in different words, and a word matcher is blind to it.

### What an embedding is

A function: text in, a list of numbers out.

```
"solar is the cheapest electricity"  →  [0.031, -0.118, 0.204, ...]   (384 numbers)
```

Those numbers are a **vector**, best understood as *coordinates*. Latitude and longitude
place a city in 2-D space, where nearby coordinates mean geographically close. An embedding
places a **sentence** in 384-dimensional space, where **nearby coordinates mean similar
meaning**.

**Why 384 dimensions and not 2?** Meaning varies along many independent axes at once —
topic, specificity, sentiment, tense, entity type. Two numbers cannot hold those apart; a
few hundred can.

Nobody designs those axes. The model is trained on millions of sentence pairs labeled
"these mean the same / these don't" and learns an arrangement satisfying them. Ours is
**`all-MiniLM-L6-v2`**: 384 dimensions, 256-token input limit, CPU-fast.

### Measuring similarity

Once sentences are points, "similar" becomes geometry: the **angle** between two vectors.
Small angle → similar meaning. That is **cosine similarity**, ~0 (unrelated) to 1 (identical).

Because we L2-normalise every vector to length 1, the cosine *is* the dot product — one
multiply. That is why search is fast, and why scores are directly comparable.

### Measured on our own encoder

```
CLAIM: "solar became the cheapest source of new electricity generation"

 cosine  word overlap   comparison
  0.747         0.133   paraphrase, almost no shared words   ← the whole point
  0.833         0.250   paraphrase, some shared words
  0.485         0.133   shares "electricity/generate", different topic
  0.931         0.800   same words, reordered
  0.013         0.056   unrelated ("my cat has been sleeping on the couch")
```

Row 1 is the justification for dense retrieval: **0.747 similarity at 0.133 word overlap.**
Row 3 shows it is not merely counting shared vocabulary — nuclear reactors share
"electricity" and "generate" yet score 0.485, well under the real paraphrases.

---

## 8. Indexing (and how it differs from caching)

**Indexing = embed everything in advance and save the result.**

Embedding is slow-ish. Re-embedding 458 passages on every query would make each search take
seconds. So it happens **once**:

```
458 passages ──embed──▶ a 458 × 384 matrix ──save──▶ data/index/vectors.npy
```

At query time we embed only the claim — **one** vector — and compare it against the stored
matrix in a single multiply. That saved bundle (`vectors.npy` + `passages.jsonl`) **is** the
index. In our system it is literally a matrix plus a list; nothing more exotic (**D-07**).

### The asymmetry: the claim is never indexed

```
corpus passages:  embedded ONCE      → saved to disk → reused for every query
the claim:        embedded PER QUERY → used for one search → discarded
```

The claim vector is transient. It is never stored, because we never search *for* it — we
search *with* it. Only the things we want to find get indexed.

### Index vs cache

|  | Cache | Index |
|---|---|---|
| Populated | lazily, on a miss | deliberately, up front |
| Contents | whatever happened to be requested | everything, exhaustively |
| Lookup key | the **exact** input seen before | a **novel** input, by nearness |
| Answers | "have I computed this already?" | "which stored item is closest to this?" |
| Evictable | yes | no — eviction breaks correctness |

Both avoid recomputation, so the intuition is sound. But **a cache only helps on a repeat of
an identical input.** Our index answers a question about claims it has never seen: *which of
my 458 passages is nearest to this brand-new sentence?* A cache structurally cannot do that.
Enabling similarity search is the point; skipping recomputation is a side benefit.

---

## 9. Chunking

### Why chunk at all — the five reasons, strongest first

1. **Locating the relevant part.** One vector per article collapses a wide spread of
   relevance into a single number, destroying the only information retrieval exists to
   produce. Measured below.
2. **Prompt limits.** 38,148 characters cannot go into a generator prompt; 150 words can.
3. **Citation precision.** See §10.
4. **Encoder truncation.** A long text is mostly discarded anyway — 96.6% of the Paris
   Agreement article, measured below.
5. **Dilution.** Real but modest: **0.045**. The weakest of the five.

### The truncation cliff

Truncation is **not** a gradient to shrink out of. It is a cliff:

```
chunk ≤ 256 tokens  →  nothing dropped. Zero.
chunk > 256 tokens  →  everything past 256 silently discarded.
```

Once under the limit you are **done**; shrinking further buys nothing. Ours measures
**190 tokens against a 256 limit — 66 headroom**, verified by `rag.cli budget`.

How brutal the cliff is, feeding the raw 7,477-token article to the encoder:

```
raw article in one go   0.675   ← encoder saw the first 256 of 7,477 tokens
```

A perfectly respectable score **while discarding 96.6% of the article.** Nothing errored.
This is why the bug class is dangerous and why `budget` exits non-zero on failure.

> **This already bit us once.** The first chunker used 220-word passages (~290 tokens), so
> the tail of every long passage was dropped from the index while retrieval kept *appearing*
> to work. A second bug sat underneath: the MediaWiki plaintext extract puts each paragraph
> on one line, so paragraph-at-a-time chunking could not bound passage size at all — a
> 600-word paragraph passed through whole. Both are now regression-tested (**D-06**).

### The cost of going smaller — yes, semantics suffer

1. **Passages stop standing alone.** Cut too fine and you get *"It was adopted in 2015."*
   Adopted *what*? The referent was in the previous chunk. The encoder and the generator both
   see an uninterpretable fragment — and the generator may cite it as evidence for something
   it cannot support.
2. **Weaker embedding signal.** 384 numbers summarizing 8 words is mostly noise; summarizing
   150 words carries real signal.
3. **Top-k crowding.** More chunks means the 5 results become 5 adjacent slivers of one
   paragraph instead of 5 distinct pieces of evidence — losing diversity exactly where it
   matters.
4. **Citations get uselessly granular.** A single cited sentence gives a viewer no context to
   judge it.

Going larger costs dilution plus the truncation cliff.

**So chunk size is a window, not a direction.** The hard ceiling is the encoder's 256 tokens.
Within that, **150 words / 35 overlap** balances "precise enough to cite" against "enough
context to stand alone". The overlap is insurance for evidence straddling a boundary.

---

## 10. Why citation precision depends on chunking

**The thing you retrieve is the thing you cite** — they are the same object. So chunk
granularity *becomes* citation granularity. That is the link.

Suppose a note says:

> "Nuclear power has caused fatal accidents, including Chernobyl in 1986."

**If the retrieval unit were the whole article**, the best citation available is:

> *Source: [Nuclear power](https://en.wikipedia.org/wiki/Nuclear_power)*

A viewer wanting to check that must now read ~10,000 words hunting for the relevant sentence.
In practice nobody does, so the citation is **decorative** — it looks like evidence without
functioning as evidence.

**Because we chunk**, we retrieved a specific 150-word passage, so we can cite:

> *Source: Nuclear power — "Accidents" section · revision 1377638624*

Checking now takes ten seconds: click, land on the right section of the exact version we
read, see whether it says what the note claims.

That precision was impossible with whole-article retrieval — **not because citing precisely
is hard, but because we would never have identified which part was relevant.** Chunking
produces that knowledge; the citation inherits it.

**It matters doubly for our metric.** The grounding check (D-05) asks whether each sentence
of a note is supported by its cited evidence. If a citation is an entire article, "supported
by" is unanswerable — almost anything is arguably "in" 10,000 words. Precise citations are
what make the central metric computable at all.

---

## 11. Retrieval is arithmetic

Not SQL. Not prompting. The whole search, from `rag/store/numpy_store.py`:

```python
scores = self._matrix @ np.asarray(query, dtype=np.float32)   # ← the entire search
top = np.argpartition(-scores, k - 1)[:k]
top = top[np.argsort(-scores[top])]
```

One matrix multiply: `(458 × 384) @ (384,)` → 458 scores. Sort, take top 5. Milliseconds.
No query language, no model, and **deterministic** — which is why recall numbers will be
stable run to run.

Three mechanisms that are easy to conflate, kept separate:

| Operation | Mechanism | Where |
|---|---|---|
| **Search** | dot product in NumPy | `rag/store/numpy_store.py` |
| **Storage** | files (`.npy` + `.jsonl`) now; SQL later via pgvector | `data/index/` |
| **Generation** | prompting an LLM | step 5 — **not built** |

**Prompting happens only at generation.** Retrieval never prompts anything. SQL enters only
on the pgvector swap (**D-02**), and then it is `ORDER BY embedding <=> query LIMIT 5` — the
same dot product, computed inside Postgres.

### Three retrievers, because scores are not comparable across them

- **dense** — embedding similarity. Cosine, 0–1.
- **bm25** — lexical. **Unbounded**; 30–40 is normal.
- **hybrid** — reciprocal rank fusion of the two. Small values (~0.03) because RRF sums
  `1/(60 + rank)`.

**A hybrid score of 0.033 is a first-place result, not a bad one.** Compare **ranks** across
retrievers, never raw scores. Why three at all: see §5 — a baseline is what makes a recall
number mean anything (**D-03**, **D-08**).

---

## 12. The generator

**The generator is the LLM that writes the note text** — the **G** in RAG.

| | |
|---|---|
| Model | **Llama 3.2, 3B parameters** |
| Served by | **Ollama**, on our own machine (`llama3.2:latest`, 2.0 GB) |
| Reached via | `http://localhost:11434` — local HTTP, not the internet |
| Status | **not built** (step 5) |

### No Claude API. No hosted API. No keys.

Three separate things happen, none of them a paid API:

1. **Fetching Wikipedia** — plain HTTP to the free MediaWiki API (`rag/corpus/wikipedia.py`).
   No key, no cost, no AI. Runs **once**, at `build` time.
2. **Retrieval** — local arithmetic. No network at all (§11).
3. **Generation** — local Llama 3.2 via Ollama.

**Why local, from the proposal:** batch-processing hundreds of hour-long transcripts would
let per-token pricing dominate the project budget, and a pinned local model means results do
not drift when a provider silently updates. This is the reason the component is reproducible.

### Risk to keep in view

3B is small. Small models honour "cite only these passages" and "do not declare the speaker
right or wrong" unreliably — and those are the *core* constraints of this component.
Mitigations in order: structured JSON output, few-shot examples, then a larger local model if
the hardware allows. A finding that a 3B model **cannot** be held to grounding constraints is
itself a reportable result.

---

## 13. What RAG actually buys us

RAG = **retrieve** relevant text, then **generate** conditioned on it.

The shift it produces is the whole point:

| | Model asked to **recall** | Model asked to **summarize** |
|---|---|---|
| Prompt | "What do you know about the Paris Agreement?" | "Here are 3 passages. Summarize what they say." |
| Relies on | weights — memory | the prompt — supplied text |
| Fails as | fluent invention | mis-summary of visible text |
| Checkable? | **no** | **yes — the evidence is right there** |

Two properties make this RAG rather than clever prompting:

1. **The facts come from the prompt**, bypassing the model's weakest faculty.
2. **Citations are machine-checkable.** `[1]` maps to a specific passage we still hold, so we
   can verify afterwards whether the note's claims are actually in `[1]`. Impossible for an
   unaided model.

### The experiment inside the architecture

Generation runs in **two conditions**, and the comparison is this component's headline result:

| Condition | Model sees | Role |
|---|---|---|
| **RAG** | claim + retrieved passages | the system |
| **LLM-only** | claim alone | the control |

Then: per sentence of each note, is it supported by cited evidence? Hypothesis — LLM-only
notes are fluent and partly invented; RAG notes are duller and more supported. This is why
the proposal calls our component *"the heart of the Community Notes idea."*

---

## 14. Abstention: the open hole

**Retrieval always returns `k` results**, even when the corpus holds nothing relevant —
cosine similarity always has a top-k. Measured:

| Claim | Corpus coverage | Top dense score |
|---|---|---|
| "the paris agreement was adopted in 2015" | covered | **0.657** |
| "the roman empire fell in 476 ad" | absent | **0.166** (returns Chernobyl passages) |

That is **expected behaviour, not a bug.** The corpus has nothing about Rome, so the nearest
neighbours are merely the least-distant irrelevant things.

**Why it matters more than it looks.** Feed those 0.166 passages to the generator and it will
dutifully write a grounded-*looking* note citing irrelevant evidence — the exact failure the
whole design exists to prevent. The proposal's own framing ("a note that confidently
misdescribes what a creator said is worse than no note") makes abstention a **correctness
requirement**, not a nicety. D-05's grounding check catches an ungrounded note after the
fact; abstention prevents generating it.

The separation is a factor of four, so a threshold is clearly viable — but it must come off
the **labeled eval set**, not from eyeballing two examples. A cutoff tuned on hand-picked
examples is a number we cannot defend in the report. Tracked as **D-09**, deferred to step 4.

---

## 15. The two answer keys — neither exists yet

No off-the-shelf dataset covers "context-worthy factual claims in YouTube transcripts,"
because the category is specific to this project. The proposal says so:

> "For Community Notes, we will **create our own smaller annotated dataset** of transcript
> segments, labeling which segments contain factual claims and which claims would benefit
> from additional context. This annotation is specific to our problem."

There are **two separate** hand-built answer keys:

| | Mikko's | **Ours** |
|---|---|---|
| Labels | segment → is it context-worthy? | claim → which passages are relevant? |
| Measures | precision / recall / F1 of the detector | **recall@k** of retrieval |
| Owner | Member 2 | **Member 3** |
| Size | ~200 segments | 40–60 claims |
| Exists? | no | **no ← our blocker (step 3)** |

**The 8 records in `fixtures/` are not an evaluation set.** They are hand-invented examples
for exercising code paths (**D-02**). An evaluation set needs real segments from videos we
did not cherry-pick, labeled against written guidelines. Without it, nothing in this
component has a defensible number.

---

## 16. Clarifications and corrections on the record

Things that were wrong or unclear, and what they are now.

### C-1 · "Validating things said in a video" → contextualizing them

**Asked:** whether this component validates claims made in a video.

**Correction:** no. It adds cited context and **deliberately withholds any verdict** on
whether the speaker is right. See §1. This changes the success metric from "is the verdict
correct?" to "is the note supported by its citations and useful?"

### C-2 · Dilution is real but modest — an earlier overstatement, corrected by measurement

**Originally claimed:** one vector per article would "sit near none of its topics" and match
a specific claim "only weakly."

**Measured, on the Paris Agreement article (53 chunks):**

```
best single chunk          0.707   ← "Effectiveness" section
mean of all chunk vectors  0.662   ← one vector for the whole article
dilution cost              0.045
chunks scoring above the averaged vector:  2 / 53
score spread across chunks:  min 0.141   max 0.707
```

**Corrected:** the averaged vector beats **51 of 53** individual chunks and is a perfectly
decent *topic-level* match. "Sits near none of them" was wrong; the real cost is 0.045.

**What the measurement actually shows** is the stronger argument: a single number cannot
express a **0.141 – 0.707 spread**. One vector per article says *"this article is somewhat
about your claim"* — which we mostly knew. It cannot say **which of the 53 pieces to read**,
and that is the only thing retrieval is for. Dilution dropped from the strongest reason to
chunk to the weakest (§9).

### C-3 · "Passage" is local, pre-downloaded text — not live web data

A passage is a ~150-word chunk of a Wikipedia article already on disk. Wikipedia is fetched
**once** at `build` time; query-time retrieval touches no network. See §2.

### C-4 · No Claude API, no hosted API, no keys

Wikipedia comes over its free public HTTP API; generation runs on local Llama 3.2 via Ollama.
Nothing in the pipeline calls a paid API. See §12.

### C-5 · Querying is neither SQL nor prompting

It is a NumPy dot product. SQL appears only after the pgvector swap; prompting appears only
at generation. See §11.

### C-6 · The claim vector is not indexed

Only corpus passages are indexed. The claim is embedded per query and discarded. See §8.

### C-7 · Truncation is a cliff, not a gradient

The fix is not progressively smaller chunks — it is being **under 256 tokens**, after which
the problem is fully solved. Ours sits at 190 with 66 headroom. Going smaller than necessary
costs context and standalone interpretability. See §9.

### C-8 · Citation precision is *downstream* of chunk granularity

You cite what you retrieve, so retrieving coarse means citing coarse — and a whole-article
citation is decorative rather than checkable. See §10.

---

## 17. Measured numbers in one place

All taken from our own system, reproducible via `rag.cli`.

| Quantity | Value |
|---|---|
| Encoder | `all-MiniLM-L6-v2`, 384 dims, 256-token limit |
| Chunk target / overlap | 150 words / 35 words |
| Chunk size in tokens | **190** (limit 256, headroom 66) |
| Corpus | 7 articles → **458 passages**, 324K on disk |
| Index | 1.1M (`vectors.npy` + `passages.jsonl`) |
| Paris Agreement article | 38,148 chars · 7,477 tokens · 53 chunks |
| Dense score, covered claim | **0.657 – 0.707** |
| Dense score, uncovered claim | **0.166** |
| BM25 score range | unbounded; **30–40** typical |
| Hybrid (RRF) top score | **~0.033** — this is *first place* |
| Paraphrase, no shared words | cosine **0.747** at word overlap **0.133** |
| Unrelated sentence | cosine **0.013** |
| Dilution cost (chunk vs article mean) | **0.045** |
| Generator | Llama 3.2, 3B, 2.0 GB, local via Ollama |
| Tests | 11 passing |

---

## 18. Glossary

| Term | Meaning here |
|---|---|
| **abstention** | Returning *no* evidence when nothing relevant exists. **Not implemented** (D-09). |
| **BM25** | Lexical ranking function; our retrieval baseline. Unbounded scores. |
| **chunk / passage** | A ~150-word piece of a reference article, carrying provenance. |
| **claim** | A transcript segment the detector marked context-worthy. |
| **context-worthy** | Checkable **and** a viewer would gain from outside information. |
| **cosine similarity** | Angle between two vectors; ~0 unrelated, 1 identical. Our dot product. |
| **dense retrieval** | Search by embedding similarity rather than word overlap. |
| **detector** | Mikko's classifier deciding which segments need a note. Not a downloadable tool. |
| **dilution** | Loss of specificity when many topics average into one vector. Measured: 0.045. |
| **embedding** | A function mapping text to a vector whose position encodes meaning. |
| **evidence corpus** | Our pinned Wikipedia subset. Same thing as "reference material". |
| **F1** | Harmonic mean of precision and recall. |
| **generator** | The LLM writing note text — Llama 3.2, local. The "G" in RAG. |
| **grounding** | Whether a note's statements are actually supported by its cited evidence. |
| **index** | Precomputed, saved vectors enabling similarity search over novel queries. |
| **L2-normalised** | Scaled to length 1, so cosine similarity equals the dot product. |
| **Ollama** | Local model server; runs Llama 3.2 on our machine. |
| **pgvector** | Postgres extension for vector search. The later swap target (D-02). |
| **precision** | Of what was flagged, the fraction correct. |
| **provenance** | Title, section, URL, revision ID — what makes a passage citable. |
| **RAG** | Retrieve relevant text, then generate conditioned on it. |
| **recall** | Of what should have been flagged, the fraction caught. |
| **recall@k** | Whether relevant evidence appears in the top k results. **Our headline metric.** |
| **revision ID** | Wikipedia's version number; what makes a citation reproducible. |
| **RRF** | Reciprocal rank fusion — combines rankings, not scores (D-08). |
| **token** | Word-piece unit the encoder counts. ~150 English words ≈ 190 tokens. |
| **truncation** | Silent discarding of input past the encoder's limit. The dangerous bug class. |
| **vector** | A list of numbers; here 384 of them, treated as coordinates in meaning-space. |
