"""Ranking metrics for retrieval evaluation.

These produce the numbers that go in the report, so they are kept small,
pure, and separately tested. Everything takes the same two arguments:

    ranked    passage keys in the order the retriever returned them
    relevant  the set of keys a human judged relevant for this claim

**recall@k is the committed metric.** The proposal promises to "measure
whether relevant evidence appears in the top-k results"; the rest are here
because they are nearly free once labels exist and they answer different
questions:

  recall@k     did we find the evidence at all?        (coverage)
  precision@k  how much of what we showed was useful?  (noise)
  MRR          how far down was the first good hit?    (effort for the reader)
  nDCG@k       are good hits near the top?             (rank quality)

A claim with no relevant passages in its pool is undefined for every metric
here and is skipped by the aggregator rather than scored as 0 -- counting it
as a miss would punish the retriever for a labeling gap.
"""

from __future__ import annotations

import math


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Fraction of known-relevant passages appearing in the top k."""
    if not relevant:
        raise ValueError("recall is undefined with no relevant passages")
    found = len(set(ranked[:k]) & relevant)
    return found / len(relevant)


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the top k that are relevant.

    Divides by k, not by len(ranked[:k]), so returning fewer than k results
    is penalised rather than silently rewarded.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    return len(set(ranked[:k]) & relevant) / k


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    """1 / rank of the first relevant hit; 0.0 if none appear."""
    for i, key in enumerate(ranked, start=1):
        if key in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Normalised discounted cumulative gain with binary relevance.

    Rewards putting relevant passages near the top: a hit at rank 1 is worth
    1/log2(2) = 1.0, at rank 5 only 1/log2(6) = 0.39. The ideal ranking puts
    every relevant passage first, capped at k.
    """
    if not relevant:
        raise ValueError("nDCG is undefined with no relevant passages")

    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, key in enumerate(ranked[:k], start=1)
        if key in relevant
    )
    ideal = sum(
        1.0 / math.log2(i + 1)
        for i in range(1, min(len(relevant), k) + 1)
    )
    return dcg / ideal if ideal else 0.0
