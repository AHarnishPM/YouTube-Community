"""Retrieval: dense, lexical, and a fusion of the two.

Three retrievers rather than one because of DESIGN-LOG D-03. The proposal
promised a retrieval evaluation but no retrieval *baseline*, which leaves
"recall@5 = 0.62" uninterpretable -- good or bad depends entirely on what plain
keyword search achieves. BM25 supplies that reference point, and the hybrid
tests whether the two signals are complementary.

They share one interface so an ablation is a flag, not a code branch.
"""

from __future__ import annotations

import re
from typing import Protocol

from rag.embed import embed_query, embed_texts
from rag.models import EvidencePassage, RetrievalResult
from rag.store.numpy_store import NumpyVectorStore

_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, for BM25 only.

    Auto-generated captions arrive without punctuation or casing, so there is
    little structure to preserve here anyway.
    """
    return _WORD.findall(text.lower())


def _require_claim(claim: str) -> str:
    """Reject an empty claim rather than retrieving for it.

    An empty string still produces a vector, and dense search happily returns
    its nearest neighbours (measured: top score 0.136). Those are pure noise,
    and silently passing them downstream would let the generator cite them as
    evidence. An empty claim is a caller bug, so it raises.
    """
    text = (claim or "").strip()
    if not text:
        raise ValueError("empty claim: nothing to retrieve evidence for")
    return text


class Retriever(Protocol):
    name: str

    def retrieve(self, claim: str, k: int) -> list[RetrievalResult]: ...


class DenseRetriever:
    """Embedding similarity. The approach the proposal commits to."""

    name = "dense"

    def __init__(self, store: NumpyVectorStore) -> None:
        self.store = store

    def retrieve(self, claim: str, k: int = 5) -> list[RetrievalResult]:
        claim = _require_claim(claim)
        hits = self.store.search(embed_query(claim), k)
        return [
            RetrievalResult(passage=p, score=s, retriever=self.name) for p, s in hits
        ]


class BM25Retriever:
    """Lexical baseline (D-03).

    Expected to be competitive precisely where claims name specific entities --
    "Paris Agreement", "400 parts per million" -- and to fail where a claim is
    paraphrased relative to the evidence. That contrast is the interesting part.
    """

    name = "bm25"

    def __init__(self, passages: list[EvidencePassage]) -> None:
        from rank_bm25 import BM25Okapi

        self.passages = passages
        self._bm25 = BM25Okapi([tokenize(p.text) for p in passages])

    def retrieve(self, claim: str, k: int = 5) -> list[RetrievalResult]:
        claim = _require_claim(claim)
        scores = self._bm25.get_scores(tokenize(claim))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]

        # A score of 0 means *no* query term appears in the passage. Returning
        # it would hand the generator a passage with literally zero lexical
        # connection to the claim and label it evidence. Unlike dense
        # retrieval, where "irrelevant" is a fuzzy judgement about distance,
        # BM25 states it exactly -- so drop those rather than pad to k.
        return [
            RetrievalResult(
                passage=self.passages[i], score=float(scores[i]), retriever=self.name
            )
            for i in order
            if scores[i] > 0.0
        ]


class HybridRetriever:
    """Reciprocal rank fusion of dense and BM25.

    RRF combines *ranks*, not scores, which sidesteps the fact that cosine
    similarity and BM25 live on incomparable scales -- no normalisation to tune
    and therefore no hidden hyperparameter doing the work.
    """

    name = "hybrid"

    def __init__(
        self,
        dense: DenseRetriever,
        bm25: BM25Retriever,
        *,
        rrf_k: int = 60,
        pool: int = 50,
    ) -> None:
        self.dense = dense
        self.bm25 = bm25
        self.rrf_k = rrf_k  # 60 is the value from the original RRF paper.
        self.pool = pool

    def retrieve(self, claim: str, k: int = 5) -> list[RetrievalResult]:
        claim = _require_claim(claim)

        # Each run contributes at most `pool` candidates, so a pool smaller
        # than k silently caps the result (asked 99, got 60). Widen it instead:
        # an evaluation computing recall@k would otherwise read short and the
        # shortfall would look like a retrieval failure.
        pool = max(self.pool, k)
        runs = [
            self.dense.retrieve(claim, pool),
            self.bm25.retrieve(claim, pool),
        ]

        fused: dict[str, float] = {}
        seen: dict[str, EvidencePassage] = {}
        for run in runs:
            for rank, hit in enumerate(run, start=1):
                pid = hit.passage.passage_id
                seen[pid] = hit.passage
                fused[pid] = fused.get(pid, 0.0) + 1.0 / (self.rrf_k + rank)

        top = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        return [
            RetrievalResult(passage=seen[pid], score=score, retriever=self.name)
            for pid, score in top
        ]


# --------------------------------------------------------------------------


def build_store(passages: list[EvidencePassage]) -> NumpyVectorStore:
    """Embed and index passages."""
    store = NumpyVectorStore()
    store.add(passages, embed_texts([p.text for p in passages]))
    return store
