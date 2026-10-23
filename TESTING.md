# Testing the retrieval pipeline by hand

How to drive the component yourself, what it is *supposed* to do, and how to tell a
real failure from expected behaviour.

> **What exists today:** the pipeline runs **claim → retrieved evidence**. Note
> generation (step 5) is not built yet, so nothing produces note text so far. Everything
> below tests retrieval.

## Setup

The virtualenv is already built at `.venv/`. Nothing to install.

```bash
cd "CS 4701/YouTube-Community"
./.venv/bin/python -m rag.cli --help
```

Every command below is `./.venv/bin/python -m rag.cli <command>`. The first command that
touches the encoder downloads it (~90 MB, once).

The index is already built and committed-adjacent in `data/index/`, so you can go straight
to `search`. Rebuild only if you want to change the corpus.

## The commands

| Command | What it does |
|---|---|
| `demo` | Narrated walkthrough of the whole component — start here, and use it to show the team |
| `stats` | Describe the saved index — passage count, size distribution, pinned revisions |
| `budget` | Check our chunk size against the encoder's token limit |
| `search "<claim>"` | Retrieve evidence for one claim you type |
| `claims` | Run the fixture claims through, as the real pipeline will |
| `build` | Re-chunk, re-embed, re-index (`--pinned` reuses the committed corpus) |
| `drift` | Check whether pinned articles have changed on Wikipedia |
| `pool` / `label` / `eval` | The retrieval evaluation — see below |

Useful flags: `-k N` for how many results, `--retriever dense|bm25|hybrid|all`, and
`--text` to print the actual passage text rather than just citations.

---

## What it is supposed to do

### 1. Retrieval: claim in, citable evidence out

```bash
./.venv/bin/python -m rag.cli search "the paris agreement was adopted in 2015" -k 3 --text
```

**Intended behaviour.** Given a factual claim pulled from a transcript, return the `k`
passages from the pinned corpus most likely to inform a viewer about it. Every result must
carry enough provenance to become a citation: article title, section, URL, and the
revision ID that identifies the exact text we retrieved.

**What correct looks like.** Results come from the obviously right article, and scores sit
around **0.6–0.75**. The URL ends `?oldid=<revision>` and resolves to the version we
indexed, not today's version.

```
  dense:
    1. [0.6574] Paris Agreement / (lead)
       https://en.wikipedia.org/wiki/Paris_Agreement?oldid=1378148547
```

**`(lead)`** means the passage came from the article's opening, before any section heading.
That is normal, not a missing label.

**Duplicate-looking hits are expected.** Two results from `Paris Agreement / (lead)` are
two different overlapping passages, not a bug — chunks overlap by 35 words by design, so
adjacent passages share context. Add `--text` to see they differ.

### 2. The three retrievers should disagree

```bash
./.venv/bin/python -m rag.cli search "the international energy agency said solar is the cheapest electricity" --retriever all -k 3
```

**Intended behaviour.** `dense` matches on meaning, `bm25` on words, `hybrid` fuses their
rankings. They are not meant to agree — the disagreement *is* the measurement (DESIGN-LOG
D-03).

**What to look for:**

- **Entity-heavy claims** ("Paris Agreement", "400 parts per million") — both do well; BM25 is often sharper, since the claim contains the exact words the article uses.
- **Paraphrased claims** — dense should win. BM25 cannot match "cheapest electricity" against "lowest-cost generation" because no words overlap.
- **Vocabulary traps** — dense should win. On the solar-costs claim, BM25 retrieves *Nuclear power / Current prospects*, misled by "power"/"energy" overlap, while dense correctly finds the IEA.

Scores are **not comparable across retrievers**. Dense is cosine similarity in 0–1. BM25 is
unbounded (values of 30–40 are normal). Hybrid returns small RRF scores (~0.03) because RRF
sums `1/(60+rank)` — a hybrid score of 0.033 is a *first-place* result, not a terrible one.
Compare ranks across retrievers, never scores.

### 3. The detector gate decides what reaches retrieval

```bash
./.venv/bin/python -m rag.cli claims
```

**Intended behaviour.** Retrieval does not decide what deserves a note — Member 2's
detector does. This command performs the real join: take the fixture segments, keep only
those marked `is_context_worthy`, and retrieve for those.

**What correct looks like.** 8 fixture segments go in, 4 pass the gate. The rejected ones
are printed first and must include the opinion ("these agreements are mostly symbolic"),
the anecdote ("my cousin works in solar"), and the sponsor read. If an opinion ever reaches
retrieval, the bug is in the gate, not in retrieval.

### 4. Chunk sizes must fit the encoder

```bash
./.venv/bin/python -m rag.cli budget
```

**Intended behaviour.** Confirm a 150-word passage encodes to fewer than 256 tokens.

**What correct looks like:** `fits: YES`, around 190 tokens, 66 headroom.

**Why this command exists.** The encoder truncates silently past 256 tokens. Our first
chunker used 220-word passages (~290 tokens), so the tail of every long passage was being
dropped from the index while retrieval still *appeared* to work. If this ever prints
`NO -- passages are being TRUNCATED`, retrieval quality is quietly broken and no other
number can be trusted. Exits non-zero so CI can catch it.

### 5. Rebuilding is reproducible

```bash
./.venv/bin/python -m rag.cli build --pinned     # reuse the committed corpus text
./.venv/bin/python -m rag.cli build              # re-fetch at current revisions
./.venv/bin/python -m rag.cli build --titles-file my_articles.txt
./.venv/bin/python -m rag.cli drift              # have pinned articles changed?
```

**Intended behaviour.** `--pinned` rebuilds the index from the **committed** corpus text in
`data/corpus/articles.jsonl`, preserving the revisions an experiment used. Plain `build`
re-fetches whatever Wikipedia says today and writes a new manifest.

**It does not re-fetch old revisions, and cannot.** Wikipedia serves the plaintext extract
only for an article's current revision; asking for a historical one returns raw wikitext,
and asking `extracts` for a revision id silently returns today's text. That was Bug 1 — the
corpus text is committed precisely because it is unrecoverable otherwise.

**What correct looks like.** After `build --pinned`, `stats` reports the same revision IDs
as before. `drift` tells you which articles have since moved on Wikipedia — currently the
*Paris Agreement* article has, from `1378148547` to a later revision. The committed corpus
still holds the pinned text, so results stay reproducible; drift is a notice, not an error.

---

## ⚠️ The most important current behaviour: there is no abstention

Retrieval **always returns `k` results**, even when the corpus contains nothing relevant.
Cosine similarity always has a top-k. Try it:

```bash
./.venv/bin/python -m rag.cli search "the roman empire fell in 476 ad" -k 3 --retriever dense
```

Since the corpus expansion this claim now finds *Roman Empire* at **0.598** — real
evidence, because the corpus covers Roman history. To see genuine no-evidence behaviour you
need a claim nothing could support:

```bash
./.venv/bin/python -m rag.cli search "my neighbour's dog is named mr biscuits" -k 3 --retriever dense
```

That returns *Industrial Revolution* at **0.311**. **Expected behaviour, not a bug** —
cosine similarity always has a top-k.

What saves it is the score separation:

| Claim | Corpus coverage | Top score |
|---|---|---|
| "the paris agreement was adopted in 2015" | covered | **0.657** |
| "the roman empire fell in 476 ad" | **now covered** | **0.598** |
| "my neighbour's dog is named mr biscuits" | genuinely absent | **0.311** |

A factor of about two. So a threshold is plausible but not obvious — but **none is implemented yet**, and
it must not be guessed. Picking the cutoff from the labelled eval set is the right way;
picking it by eyeballing two examples is how you end up with a number you cannot defend in
the report. The eval harness below is what makes that choice defensible.

This matters more than it looks. It is the difference between a note that says *"here is
relevant context"* and one that confidently attaches Chernobyl passages to a claim about
Rome. Tracked as **D-09** in `DESIGN-LOG.md`.

## Measuring retrieval quality (the eval)

Hand-testing finds bugs; this is what finds out whether retrieval *works*. Three steps.

### 1. Build a labeling pool

```bash
./.venv/bin/python -m rag.cli pool --depth 10
```

Runs all three retrievers on every context-worthy claim and collects the **union** of their
top-10 into `data/eval/labels.json` — about 16 candidates per claim, every one unjudged.

Pooling across all three (not just the one being tested) is what keeps the comparison
honest: pooling only dense results would penalise BM25 for finding passages nobody judged.

### 2. Judge the candidates

```bash
./.venv/bin/python -m rag.cli label
```

Shows one claim-and-passage pair at a time and asks whether that passage gives a viewer
useful context on that claim. `y` / `n` / `s` to skip / `q` to save and quit — progress is
saved, so it can be done in sittings. Or edit `data/eval/labels.json` directly and set each
`"relevant"` to `true` or `false`.

**Only you can do this step.** Relevance is the human judgement the entire evaluation rests
on; labels invented by anything else measure the inventor, not the system.

### 3. Run the eval

```bash
./.venv/bin/python -m rag.cli eval                 # k = 1, 3, 5, 10
./.venv/bin/python -m rag.cli eval -k 1 5 20       # custom k
```

Reports, for each retriever:

| Metric | Question it answers |
|---|---|
| **recall@k** | did the evidence appear at all? ← **the committed metric** |
| precision@k | how much of what we showed was useful? |
| MRR | how far down was the first good hit? |
| nDCG@k | are good hits near the top? |

Plus diagnostics that matter as much as the scores:

- **unjudged fraction** — how much of what was returned was never judged. High means the
  pool was too shallow to evaluate what the retriever actually does.
- **stale keys** — labelled passages no retriever returned. Usually means chunk size changed,
  so the pool needs rebuilding. Reported rather than left to quietly deflate recall.
- **excluded claims** — unlabelled, or with nothing relevant in the pool. Scoring those as 0
  would blame the retriever for a gap in the corpus or the labels.

### Trying the harness before you have labels

```bash
./.venv/bin/python -m rag.cli pool --seed-provisional
./.venv/bin/python -m rag.cli eval
```

Auto-judges by article title so the harness can be exercised end to end. It prints a loud
`PROVISIONAL LABELS` banner, and the numbers are **not** usable: title-level relevance
ignores whether a passage bears on the claim. The giveaway is MRR coming out at exactly
1.000 for all three retrievers — not because retrieval is perfect, but because rank 1 always
came from the right article. See **D-10**.

## What is not built yet

| Step | Status |
|---|---|
| Note generation from retrieved evidence | **not built** — nothing produces note text yet |
| Abstention / no-evidence handling | **not built** — see D-09 |
| Retrieval evaluation (recall@k) | harness **built**; needs your judgements to produce a result |
| RAG vs LLM-only grounding study | **not built** — step 6 |
| FastAPI endpoint | **not built** — step 8 |
| Real transcripts / real detector | fixtures only, by design (D-02) |

So: you can inspect whether retrieval surfaces sensible evidence, but you **cannot yet**
judge note quality or grounding, because no notes are generated.

## Running the tests

```bash
./.venv/bin/python -m pytest tests/ -q      # 11 tests
```

These cover chunking invariants (provenance on every passage, no section bleed, overlap
present, oversized paragraphs split) and the fixture contracts. They do **not** test
retrieval quality — that is what step 4's evaluation is for, and it needs human labels.

## Honest limits of hand-testing

Typing claims and eyeballing results is good for catching gross breakage and for building
intuition about where dense and lexical retrieval diverge. It cannot tell you how well
retrieval works. Two reasons:

1. **You will unconsciously pick claims the corpus covers.** The seven-article demo corpus
   is about climate and energy; claims you invent will drift toward it.
2. **"Looks relevant" is not recall.** Judging the passages you were *shown* says nothing
   about relevant passages ranked 6th — which is exactly what recall@k measures.

Hand-testing is for finding bugs. Step 4 is for finding out whether it works.
