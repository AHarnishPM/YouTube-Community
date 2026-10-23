"""Run the retrieval evaluation across all retrievers.

Reports recall@k (the committed metric), precision@k, MRR and nDCG@k for
dense, BM25 and hybrid on the same labelled claims -- which is the point of
D-03: a recall number is uninterpretable until a lexical baseline sits next
to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from rag.eval.labels import LabelSet, passage_key
from rag.eval.metrics import ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank

DEFAULT_KS = (1, 3, 5, 10)


@dataclass
class RetrieverScore:
    retriever: str
    n_claims: int
    recall: dict[int, float]
    precision: dict[int, float]
    ndcg: dict[int, float]
    mrr: float
    unjudged_rate: dict[int, float]


def evaluate(
    labels: LabelSet,
    retrievers: dict,
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> tuple[list[RetrieverScore], dict]:
    """Score every retriever on the usable labelled claims.

    Returns (scores, diagnostics). Diagnostics matter as much as the scores:
    they report how many labelled keys never appeared in any result, which is
    how a stale pool (changed chunking) announces itself instead of quietly
    deflating recall.
    """
    claims = labels.usable
    if not claims:
        raise ValueError(
            "no usable claims: every claim's pool is unlabelled or has no "
            "relevant passages. Run `pool`, then judge the candidates."
        )

    max_k = max(ks)
    scores: list[RetrieverScore] = []
    all_keys_seen: set[str] = set()

    for name, retriever in retrievers.items():
        recall: dict[int, float] = {}
        precision: dict[int, float] = {}
        ndcg: dict[int, float] = {}
        unjudged: dict[int, float] = {}
        rr_total = 0.0

        # One retrieval per claim at max_k; every k is a prefix of it.
        ranked_per_claim: list[tuple[list[str], set[str], set[str]]] = []
        for claim in claims:
            hits = retriever.retrieve(claim.claim_text, max_k)
            ranked = [passage_key(h.passage.text) for h in hits]
            all_keys_seen.update(ranked)
            judged = {c.key for c in claim.candidates if c.relevant is not None}
            ranked_per_claim.append((ranked, claim.relevant_keys, judged))

        for k in ks:
            recall[k] = sum(
                recall_at_k(r, rel, k) for r, rel, _ in ranked_per_claim
            ) / len(claims)
            precision[k] = sum(
                precision_at_k(r, rel, k) for r, rel, _ in ranked_per_claim
            ) / len(claims)
            ndcg[k] = sum(
                ndcg_at_k(r, rel, k) for r, rel, _ in ranked_per_claim
            ) / len(claims)
            # Fraction of returned results that were never judged at all.
            unjudged[k] = sum(
                sum(1 for key in r[:k] if key not in judged) / max(1, len(r[:k]))
                for r, _, judged in ranked_per_claim
            ) / len(claims)

        rr_total = sum(reciprocal_rank(r, rel) for r, rel, _ in ranked_per_claim)

        scores.append(
            RetrieverScore(
                retriever=name,
                n_claims=len(claims),
                recall=recall,
                precision=precision,
                ndcg=ndcg,
                mrr=rr_total / len(claims),
                unjudged_rate=unjudged,
            )
        )

    labelled_keys = {c.key for cl in claims for c in cl.candidates}
    diagnostics = {
        "claims_total": len(labels.claims),
        "claims_usable": len(claims),
        "claims_unlabelled": sum(1 for c in labels.claims if c.judged == 0),
        "claims_no_relevant": len(labels.claims) - len(claims),
        "pool_depth": labels.pool_depth,
        "provisional": labels.provisional,
        "stale_keys": len(labelled_keys - all_keys_seen),
        "labelled_keys": len(labelled_keys),
    }
    return scores, diagnostics


def format_report(scores: list[RetrieverScore], diag: dict, ks: tuple[int, ...]) -> str:
    """Render the eval as a table, with the caveats attached."""
    lines: list[str] = []

    if diag["provisional"]:
        lines += [
            "",
            "  " + "!" * 70,
            "  !! PROVISIONAL LABELS -- these numbers are a smoke test of the",
            "  !! harness, NOT a result. Do not put them in the report.",
            "  " + "!" * 70,
        ]

    lines += [
        "",
        f"  claims scored      {diag['claims_usable']} of {diag['claims_total']}",
        f"  pool depth         {diag['pool_depth']}",
        f"  labelled passages  {diag['labelled_keys']}",
    ]
    if diag["claims_unlabelled"]:
        lines.append(f"  UNLABELLED claims  {diag['claims_unlabelled']} (excluded)")
    if diag["claims_no_relevant"]:
        lines.append(f"  no relevant found  {diag['claims_no_relevant']} (excluded)")
    if diag["stale_keys"]:
        lines.append(
            f"  STALE KEYS         {diag['stale_keys']} labelled passages never "
            "retrieved -- chunking may have changed; rebuild the pool"
        )

    width = max(len(s.retriever) for s in scores)
    for metric, attr in (("recall", "recall"), ("precision", "precision"), ("nDCG", "ndcg")):
        lines += ["", f"  {metric}@k"]
        lines.append("    " + " " * width + "".join(f"{f'@{k}':>9}" for k in ks))
        for s in scores:
            vals = getattr(s, attr)
            lines.append(
                f"    {s.retriever:<{width}}" + "".join(f"{vals[k]:>9.3f}" for k in ks)
            )

    lines += ["", "  MRR"]
    for s in scores:
        lines.append(f"    {s.retriever:<{width}}{s.mrr:>9.3f}")

    lines += ["", "  unjudged fraction of returned results (pooling blind spot)"]
    lines.append("    " + " " * width + "".join(f"{f'@{k}':>9}" for k in ks))
    for s in scores:
        lines.append(
            f"    {s.retriever:<{width}}" + "".join(f"{s.unjudged_rate[k]:>9.3f}" for k in ks)
        )

    lines += [
        "",
        "  Reading these: recall@k is the committed metric -- did the evidence",
        "  appear at all. Unjudged results count as NOT relevant, so pooled",
        "  recall is an upper bound on true recall. A high unjudged fraction",
        "  means the pool was too shallow to judge what is being returned.",
        "",
    ]
    return "\n".join(lines)
