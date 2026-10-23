"""Command line entry point for trying the retrieval pipeline by hand.

    python -m rag.cli budget
    python -m rag.cli build
    python -m rag.cli search "the paris agreement was adopted in 2015"
    python -m rag.cli claims
    python -m rag.cli stats

See TESTING.md for what each command should produce and how to read it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CORPUS_DIR = Path("data/corpus")
INDEX_DIR = Path("data/index")

# The demo corpus: enough coverage for the fixture claims, small enough to
# build in a couple of minutes.
DEFAULT_TITLES = [
    "Paris Agreement",
    "Carbon dioxide in Earth's atmosphere",
    "Solar power",
    "Chernobyl disaster",
    "Nuclear power",
    "International Energy Agency",
    "Climate change",
]


def _load_retrievers():
    """Load the saved index and build all three retrievers over it."""
    from rag.retrieve import BM25Retriever, DenseRetriever, HybridRetriever
    from rag.store.numpy_store import NumpyVectorStore

    try:
        store = NumpyVectorStore.load(INDEX_DIR)
    except FileNotFoundError:
        sys.exit(f"No index in {INDEX_DIR}. Run:  python -m rag.cli build")

    dense = DenseRetriever(store)
    bm25 = BM25Retriever(store.passages)
    return store, {
        "dense": dense,
        "bm25": bm25,
        "hybrid": HybridRetriever(dense, bm25),
    }


def _print_hits(hits, show_text: bool) -> None:
    if not hits:
        print("    (no results)")
        return
    for rank, h in enumerate(hits, 1):
        p = h.passage
        where = f"{p.title}" + (f" / {p.section}" if p.section else " / (lead)")
        print(f"    {rank}. [{h.score:.4f}] {where}")
        print(f"       {p.url}?oldid={p.revision_id}")
        if show_text:
            body = " ".join(p.text.split())
            print(f"       “{body[:300]}{'...' if len(body) > 300 else ''}”")


# --------------------------------------------------------------------------


def cmd_budget(args) -> None:
    """Check that our chunk size survives the encoder without truncation."""
    from rag.embed import MODEL_NAME, check_chunk_budget

    r = check_chunk_budget()
    print(f"encoder            {MODEL_NAME}")
    print(f"chunk target       {r['target_words']} words")
    print(f"measures as        {r['measured_tokens']} tokens")
    print(f"encoder limit      {r['model_limit']} tokens")
    print(f"headroom           {r['headroom_tokens']} tokens")
    print(f"\nfits: {'YES' if r['fits'] else 'NO -- passages are being TRUNCATED'}")
    if not r["fits"]:
        sys.exit(1)


def cmd_build(args) -> None:
    """Fetch the corpus, chunk it, embed it, save the index."""
    from rag.corpus.chunk import chunk_article
    from rag.corpus.wikipedia import (
        fetch_articles,
        load_corpus,
        write_corpus,
    )
    from rag.retrieve import build_store

    titles = DEFAULT_TITLES
    if args.titles_file:
        titles = [
            ln.strip()
            for ln in Path(args.titles_file).read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        ]

    def progress(i, total, title):
        print(f"  [{i}/{total}] {title}")

    if args.pinned:
        # Reuse the committed corpus text. Re-fetching cannot reproduce it --
        # Wikipedia serves the plaintext extract only for current revisions.
        text_path = CORPUS_DIR / "articles.jsonl"
        if not text_path.exists():
            sys.exit(f"--pinned needs the committed corpus at {text_path}")
        articles = load_corpus(text_path)
        print(f"reusing {len(articles)} articles from the committed corpus "
              f"(no re-fetch; revisions preserved)")
    else:
        print(f"fetching {len(titles)} articles from en.wikipedia.org")
        articles, failed = fetch_articles(titles, on_progress=progress)
        if failed:
            print(f"\n  WARNING: could not fetch:")
            for f in failed:
                print(f"    - {f}")
        if not articles:
            sys.exit("no articles fetched")
        write_corpus(articles, CORPUS_DIR)
        print(f"\nwrote corpus + manifest to {CORPUS_DIR}/")

    passages = []
    for a in articles:
        passages += chunk_article(
            doc_id=a.doc_id, title=a.title, url=a.url,
            text=a.text, revision_id=a.revision_id,
        )
    print(f"chunked into {len(passages)} passages")

    print("embedding (first run downloads the model)...")
    store = build_store(passages)
    store.save(INDEX_DIR)
    print(f"indexed {len(store)} passages -> {INDEX_DIR}/")


def cmd_search(args) -> None:
    """Retrieve evidence for one claim typed on the command line."""
    _, retrievers = _load_retrievers()

    names = list(retrievers) if args.retriever == "all" else [args.retriever]
    print(f"\nCLAIM: {args.claim}\n" + "=" * 72)
    for name in names:
        print(f"\n  {name}:")
        _print_hits(retrievers[name].retrieve(args.claim, args.k), args.text)
    print()


def cmd_claims(args) -> None:
    """Run the fixture claims through retrieval, as the real pipeline will."""
    from rag.fixtures import context_worthy_claims, load_detections, load_segments

    _, retrievers = _load_retrievers()
    segments, detections = load_segments(), load_detections()
    gated = context_worthy_claims(segments, detections)
    gated_ids = {c.segment_id for c in gated}

    print(f"\n{len(segments)} fixture segments; Member 2's gate passes "
          f"{len(gated)} as context-worthy.\n")
    print("Segments the gate REJECTED (these must never reach retrieval):")
    for d in detections:
        if not d.is_context_worthy:
            seg = next(s for s in segments if s.segment_id == d.segment_id)
            print(f"  - [{d.confidence:.2f}] {seg.text[:70]}...")

    names = list(retrievers) if args.retriever == "all" else [args.retriever]
    for claim in gated:
        print(f"\n{'=' * 72}")
        print(f"CLAIM {claim.segment_id} @ {claim.start:.0f}s")
        print(f"  {claim.text}")
        for name in names:
            print(f"\n  {name}:")
            _print_hits(retrievers[name].retrieve(claim.text, args.k), args.text)
    print()

    assert gated_ids, "no claims gated through -- fixtures are wrong"


def cmd_stats(args) -> None:
    """Describe the saved index."""
    import json

    store, _ = _load_retrievers()
    passages = store.passages
    words = [len(p.text.split()) for p in passages]

    print(f"indexed passages   {len(passages)}")
    print(f"distinct articles  {len({p.doc_id for p in passages})}")
    print(f"words per passage  min {min(words)}  mean {sum(words) // len(words)}  max {max(words)}")

    manifest_path = CORPUS_DIR / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        print(f"\npinned revisions ({m['fetched_count']} articles):")
        for a in m["articles"]:
            print(f"  {a['revision_id']}  {a['title']}")


def cmd_drift(args) -> None:
    """Report which pinned articles have changed on Wikipedia since we fetched."""
    from rag.corpus.wikipedia import check_drift, load_manifest

    manifest_path = CORPUS_DIR / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"no manifest at {manifest_path}")

    manifest = load_manifest(manifest_path)
    print(f"checking {len(manifest)} pinned revisions against Wikipedia...\n")
    drifted = check_drift(
        manifest,
        on_progress=lambda i, n, t: print(f"  [{i}/{n}] {t}"),
    )

    if not drifted:
        print(f"\nno drift: all {len(manifest)} articles still at their pinned revisions.")
        return

    print(f"\n{len(drifted)}/{len(manifest)} articles have changed since the corpus was built:\n")
    for title, pinned, current in drifted:
        print(f"  {title}")
        print(f"    pinned  {pinned}")
        print(f"    current {current}")
    print("\nThe committed corpus still holds the pinned text, so results remain")
    print("reproducible. This is a notice, not an error.")


def cmd_demo(args) -> None:
    """A narrated walkthrough of the component, for showing the team."""
    import numpy as np

    from rag.embed import MODEL_NAME, check_chunk_budget, embed_texts
    from rag.fixtures import context_worthy_claims, load_detections, load_segments
    from rag.retrieve import tokenize

    def head(n, title):
        print(f"\n{'=' * 74}\n  {n}. {title}\n{'=' * 74}")

    store, retrievers = _load_retrievers()

    # ---------------------------------------------------------------- 1
    head(1, "THE EVIDENCE CORPUS  (pinned Wikipedia, fetched once, offline)")
    passages = store.passages
    print(f"\n  {len({p.doc_id for p in passages})} articles -> {len(passages)} passages")
    print("  Each passage keeps enough provenance to become a citation:\n")
    p = passages[0]
    print(f"    title     {p.title}")
    print(f"    section   {p.section or '(lead)'}")
    print(f"    revision  {p.revision_id}   <- pins the exact text we read")
    print(f"    words     {len(p.text.split())}")

    # ---------------------------------------------------------------- 2
    head(2, "WHY EMBEDDINGS  (word matching cannot see paraphrase)")
    base = "solar became the cheapest source of new electricity generation"
    cmp_ = [
        ("photovoltaics now offer the lowest-cost power generation", "paraphrase, barely any shared words"),
        ("nuclear reactors also generate electricity for the grid", "shares words, different topic"),
        ("my cat has been sleeping on the couch all afternoon", "unrelated"),
    ]
    V = embed_texts([base] + [t for t, _ in cmp_])
    bt = set(tokenize(base))
    print(f"\n  claim: \"{base}\"\n")
    print(f"  {'cosine':>7}  {'word overlap':>13}   ")
    for i, (txt, note) in enumerate(cmp_, 1):
        ot = set(tokenize(txt))
        print(f"  {float(V[0] @ V[i]):7.3f}  {len(bt & ot) / len(bt | ot):13.3f}   {note}")
    print("\n  Row 1 is the point: same meaning, almost no shared words.")

    # ---------------------------------------------------------------- 3
    head(3, "THE DETECTOR GATE  (Mikko's -- decides what reaches us)")
    segs, dets = load_segments(), load_detections()
    gated = context_worthy_claims(segs, dets)
    print(f"\n  {len(segs)} transcript segments in, {len(gated)} pass as context-worthy.\n")
    for d in dets:
        seg = next(x for x in segs if x.segment_id == d.segment_id)
        mark = "PASS" if d.is_context_worthy else "    "
        print(f"    [{mark}] {seg.text[:62]}...")
    print("\n  Rejected: opinion, personal anecdote, sponsor read. None are checkable.")

    # ---------------------------------------------------------------- 4
    head(4, "RETRIEVAL  (claim -> citable evidence; one matrix multiply)")
    claim = gated[0]
    print(f"\n  claim @ {claim.start:.0f}s: \"{claim.text[:66]}...\"\n")
    for name in ("dense", "bm25", "hybrid"):
        hits = retrievers[name].retrieve(claim.text, 2)
        print(f"    {name}:")
        for h in hits:
            where = h.passage.title + (f" / {h.passage.section}" if h.passage.section else " / (lead)")
            print(f"      [{h.score:.3f}] {where}")
    print("\n  Scores are NOT comparable across retrievers: dense is cosine 0-1,")
    print("  BM25 is unbounded, hybrid RRF sums 1/(60+rank) so ~0.03 is FIRST place.")

    # ---------------------------------------------------------------- 5
    head(5, "THE OPEN HOLE: NO ABSTENTION  (D-09)")
    off = "the roman empire fell in 476 ad after the sack of ravenna"
    cov = retrievers["dense"].retrieve(claim.text, 1)[0]
    unc = retrievers["dense"].retrieve(off, 1)[0]
    print(f"\n  covered claim    {cov.score:.3f}   {cov.passage.title}")
    print(f"  uncovered claim  {unc.score:.3f}   {unc.passage.title}   <- irrelevant, still returned")
    print(f"\n  Separation is {cov.score / unc.score:.1f}x, so a threshold is viable --")
    print("  but it must come off the labeled eval set, not from two examples.")
    print("  Until then the generator would cite irrelevant evidence confidently.")

    # ---------------------------------------------------------------- 6
    head(6, "THE SILENT-FAILURE GUARD")
    b = check_chunk_budget()
    print(f"\n  encoder {MODEL_NAME}")
    print(f"  {b['target_words']}-word passages measure {b['measured_tokens']} tokens "
          f"(limit {b['model_limit']}, headroom {b['headroom_tokens']})")
    print(f"  fits: {'YES' if b['fits'] else 'NO -- PASSAGES ARE BEING TRUNCATED'}")
    print("\n  Past the limit the encoder drops the tail SILENTLY: retrieval keeps")
    print("  working, just worse. This check is why that cannot happen unnoticed.")

    print(f"\n{'=' * 74}")
    print("  NOT BUILT YET: note generation, abstention, recall@k evaluation.")
    print("  Nothing produces note text so far -- this ends at retrieved evidence.")
    print(f"{'=' * 74}\n")


# Document-level relevance for the fixture claims, used ONLY to smoke-test the
# eval harness. Judging a passage relevant because it came from the right
# article is far too coarse to report -- it ignores whether the passage
# actually bears on the claim. Real labels are judged per passage, by hand.
PROVISIONAL_TITLES = {
    "fx001-1": {"Paris Agreement"},
    "fx001-3": {"Carbon dioxide in the atmosphere of Earth"},
    "fx001-5": {"Solar power", "International Energy Agency"},
    "fx001-7": {"Chernobyl disaster", "Nuclear power"},
}


def cmd_pool(args) -> None:
    """Build a labeling worksheet from every retriever's top results."""
    from rag.eval.labels import LABELS_PATH, build_pool
    from rag.fixtures import context_worthy_claims

    _, retrievers = _load_retrievers()

    claims = [(c.segment_id, c.text) for c in context_worthy_claims()]
    print(f"pooling top-{args.depth} from {len(retrievers)} retrievers "
          f"for {len(claims)} claims...")

    labels = build_pool(claims, retrievers, depth=args.depth)

    if args.seed_provisional:
        n = 0
        for claim in labels.claims:
            allowed = PROVISIONAL_TITLES.get(claim.claim_id)
            if allowed is None:
                continue
            for cand in claim.candidates:
                cand.relevant = cand.title in allowed
                n += 1
        labels.provisional = True
        labels.note = (
            "SMOKE TEST ONLY. Auto-labelled by article title, not by reading "
            "the passages. Document-level relevance ignores whether a passage "
            "actually bears on the claim. Replace by hand before reporting."
        )
        print(f"  seeded {n} provisional judgements by article title")
    else:
        labels.note = "Judge each candidate by hand: set relevant to true or false."

    labels.save(LABELS_PATH)

    total = sum(len(c.candidates) for c in labels.claims)
    print(f"\nwrote {LABELS_PATH}")
    print(f"  {len(labels.claims)} claims, {total} candidate passages "
          f"({total / len(labels.claims):.1f} per claim)")
    if not args.seed_provisional:
        print(f"\nNext: judge them with  python -m rag.cli label")
        print(f"      or edit {LABELS_PATH} directly (set \"relevant\": true/false)")


def cmd_label(args) -> None:
    """Judge pooled candidates one at a time.

    Saves after every judgement. Labelling is hours of irreplaceable human
    work, so a dropped terminal, a Ctrl-C or an end-of-input must never cost
    more than the item in progress.
    """
    from rag.eval.labels import LABELS_PATH, LabelSet

    if not LABELS_PATH.exists():
        sys.exit(f"no pool at {LABELS_PATH}. Run:  python -m rag.cli pool")

    labels = LabelSet.load(LABELS_PATH)
    todo = [
        (cl, cand)
        for cl in labels.claims
        for cand in cl.candidates
        if cand.relevant is None or args.redo
    ]
    total_all = sum(len(c.candidates) for c in labels.claims)

    if not todo:
        print(f"all {total_all} candidates are judged. Run:  python -m rag.cli eval")
        return

    def persist() -> None:
        # Only a fully judged set stops being provisional -- otherwise `eval`
        # would drop its warning banner while most candidates are unjudged.
        labels.provisional = not all(cl.is_complete for cl in labels.claims)
        labels.note = (
            "Hand-judged." if not labels.provisional
            else "Hand-judging in progress; some candidates are still unjudged."
        )
        labels.save(LABELS_PATH)

    print(f"{len(todo)} of {total_all} candidates to judge.")
    print("For each: does this passage give a viewer useful context on the claim?")
    print("  y = relevant   n = not relevant   s = skip   q = save and quit")
    print("Progress is saved after every answer, so you can stop any time.\n")

    done = 0
    try:
        for i, (claim, cand) in enumerate(todo, 1):
            print("=" * 74)
            print(f"[{i}/{len(todo)}]  CLAIM {claim.claim_id}")
            print(f"  {claim.claim_text}")
            print(f"\nPASSAGE  {cand.title}" + (f" / {cand.section}" if cand.section else ""))
            print(f"  found by: {', '.join(cand.retrievers)}")
            print(f"  {cand.snippet}")

            while True:
                ans = input("\n  relevant? [y/n/s/q] ").strip().lower()
                if ans in ("y", "n", "s", "q"):
                    break
                print("  please answer y, n, s (skip) or q (quit)")

            if ans == "q":
                break
            if ans == "s":
                continue

            cand.relevant = ans == "y"
            done += 1
            persist()

    except (EOFError, KeyboardInterrupt):
        # Ctrl-C, Ctrl-D, or a closed pipe. Everything answered is already
        # on disk; say so rather than printing a traceback over the work.
        print("\n\ninterrupted.")

    persist()
    remaining = sum(1 for c in labels.claims for d in c.candidates if d.relevant is None)
    print(f"\nsaved {done} judgement(s) to {LABELS_PATH}")
    print(f"{remaining} of {total_all} still unjudged.")
    if remaining:
        print("Run `label` again to continue where you left off.")
    else:
        print("Complete. Run:  python -m rag.cli eval")


def cmd_eval(args) -> None:
    """Score every retriever against the labels."""
    from rag.eval.labels import LABELS_PATH, LabelSet
    from rag.eval.run import evaluate, format_report

    if not LABELS_PATH.exists():
        sys.exit(f"no labels at {LABELS_PATH}. Run:  python -m rag.cli pool")

    labels = LabelSet.load(LABELS_PATH)
    _, retrievers = _load_retrievers()
    ks = tuple(args.k)

    try:
        scores, diag = evaluate(labels, retrievers, ks=ks)
    except ValueError as exc:
        sys.exit(f"{exc}")

    print(format_report(scores, diag, ks))


def main() -> None:
    ap = argparse.ArgumentParser(prog="rag", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("budget", help="check chunk size against the encoder limit").set_defaults(func=cmd_budget)

    b = sub.add_parser("build", help="fetch, chunk, embed and index the corpus")
    b.add_argument("--titles-file", help="file of article titles, one per line")
    b.add_argument("--pinned", action="store_true",
                   help="reuse the committed corpus text instead of re-fetching")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("search", help="retrieve evidence for one claim")
    s.add_argument("claim")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--retriever", choices=["dense", "bm25", "hybrid", "all"], default="all")
    s.add_argument("--text", action="store_true", help="print passage text")
    s.set_defaults(func=cmd_search)

    c = sub.add_parser("claims", help="run the fixture claims through retrieval")
    c.add_argument("-k", type=int, default=3)
    c.add_argument("--retriever", choices=["dense", "bm25", "hybrid", "all"], default="all")
    c.add_argument("--text", action="store_true")
    c.set_defaults(func=cmd_claims)

    sub.add_parser("stats", help="describe the saved index").set_defaults(func=cmd_stats)
    sub.add_parser("drift", help="check pinned revisions against Wikipedia").set_defaults(func=cmd_drift)
    sub.add_parser("demo", help="narrated walkthrough, for showing the team").set_defaults(func=cmd_demo)

    pl = sub.add_parser("pool", help="build a labeling worksheet for the eval")
    pl.add_argument("--depth", type=int, default=10, help="top-N per retriever (default 10)")
    pl.add_argument("--seed-provisional", action="store_true",
                    help="auto-judge by article title -- SMOKE TEST ONLY")
    pl.set_defaults(func=cmd_pool)

    lb = sub.add_parser("label", help="judge pooled candidates by hand")
    lb.add_argument("--redo", action="store_true", help="revisit already-judged candidates")
    lb.set_defaults(func=cmd_label)

    ev = sub.add_parser("eval", help="score retrievers against the labels")
    ev.add_argument("-k", type=int, nargs="+", default=[1, 3, 5, 10])
    ev.set_defaults(func=cmd_eval)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
